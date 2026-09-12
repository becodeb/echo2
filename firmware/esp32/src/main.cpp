// ─────────────────────────────────────────────────────────────────
// Echo Device — ESP32-S3 Meeting Companion
//
// La carita de Echo escucha la reunión y transmite el audio en streaming.
// El audio NUNCA se almacena en el dispositivo: cada frame I2S se convierte
// a PCM16 y se envía por WebSocket de inmediato.
//
// Estados (cara en OLED):
//   idle      🙂  esperando       — listo, sin reunión
//   listening 👂  escuchando      — reunión en vivo, ojos reaccionan al volumen
//   thinking  ···  procesando     — la reunión terminó, Echo procesa
//   sleeping  😴  pausado
//   done      ✓   reunión lista
//   error     ⚠   sin conexión / error
//
// Botón físico:
//   pulsación corta  — iniciar reunión / pausar / reanudar
//   pulsación larga  — finalizar reunión
//
// Onboarding: al primer arranque muestra "CODE ######"; el usuario lo ingresa
// en Echo (Ajustes → Dispositivos → Vincular). El token definitivo se guarda
// en NVS (Preferences).
// ─────────────────────────────────────────────────────────────────
#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <U8g2lib.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <driver/i2s.h>

#include "echo_config.h"

// ── Estado global ────────────────────────────────────────────────
enum class Mood { Idle, Listening, Thinking, Sleeping, Done, Error };

// prototipos
void connectAudioWs();
void startMeeting();
void finishMeeting();

U8G2_SSD1306_128X64_NONAME_F_HW_I2C display(U8G2_R0, U8X8_PIN_NONE, PIN_OLED_SCL, PIN_OLED_SDA);
Preferences prefs;
WebSocketsClient audioWs;

Mood mood = Mood::Idle;
String deviceToken;
String pairCode;
String pairPollToken;
String activeMeetingId;
bool wsConnected = false;
bool paused = false;
float audioLevel = 0.0f;
uint32_t lastHeartbeat = 0;
uint32_t lastFaceDraw = 0;
uint32_t lastPairPoll = 0;
uint32_t buttonDownAt = 0;
bool buttonWasDown = false;
uint32_t doneUntil = 0;

int16_t frameBuffer[FRAME_SAMPLES];
int32_t i2sRaw[FRAME_SAMPLES];

// ── Cara de Echo ─────────────────────────────────────────────────
void drawFace() {
  display.clearBuffer();
  const int cx1 = 44, cx2 = 84, cy = 30;

  auto eyes = [&](int height) {
    int radius = 7;
    display.drawRBox(cx1 - radius, cy - height / 2, radius * 2, height, radius - 1);
    display.drawRBox(cx2 - radius, cy - height / 2, radius * 2, height, radius - 1);
  };

  switch (mood) {
    case Mood::Idle: {
      // parpadeo ocasional
      bool blink = (millis() / 100) % 45 == 0;
      eyes(blink ? 3 : 22);
      break;
    }
    case Mood::Listening: {
      int height = 16 + (int)(audioLevel * 22.0f);
      if (height > 30) height = 30;
      eyes(height);
      display.setFont(u8g2_font_5x8_tr);
      display.drawStr(2, 62, "\xb7 GRABANDO");  // indicador SIEMPRE visible
      break;
    }
    case Mood::Thinking: {
      eyes(20);
      int dot = (millis() / 350) % 3;
      for (int i = 0; i < 3; i++) {
        if (i == dot) display.drawDisc(52 + i * 12, 52, 3);
        else display.drawCircle(52 + i * 12, 52, 3);
      }
      break;
    }
    case Mood::Sleeping: {
      display.drawHLine(cx1 - 8, cy, 16);
      display.drawHLine(cx2 - 8, cy, 16);
      display.setFont(u8g2_font_5x8_tr);
      display.drawStr(46, 55, "z Z z");
      break;
    }
    case Mood::Done: {
      // ojos felices (arcos) + sonrisa
      display.drawLine(cx1 - 8, cy, cx1, cy - 7);
      display.drawLine(cx1, cy - 7, cx1 + 8, cy);
      display.drawLine(cx2 - 8, cy, cx2, cy - 7);
      display.drawLine(cx2, cy - 7, cx2 + 8, cy);
      display.drawLine(50, 48, 58, 54);
      display.drawLine(58, 54, 70, 54);
      display.drawLine(70, 54, 78, 48);
      break;
    }
    case Mood::Error: {
      display.setFont(u8g2_font_9x15_tr);
      display.drawStr(cx1 - 8, cy + 5, "x");
      display.drawStr(cx2 - 8, cy + 5, "x");
      display.setFont(u8g2_font_5x8_tr);
      display.drawStr(20, 60, "sin conexion");
      break;
    }
  }

  // barra de estado superior
  display.setFont(u8g2_font_4x6_tr);
  if (WiFi.status() == WL_CONNECTED) {
    long rssi = WiFi.RSSI();
    display.drawStr(2, 6, rssi > -60 ? "wifi:++" : rssi > -75 ? "wifi:+" : "wifi:~");
  } else {
    display.drawStr(2, 6, "wifi:x");
  }
  display.drawStr(100, 6, ECHO_FW_VERSION);
  display.sendBuffer();
}

void drawPairScreen() {
  display.clearBuffer();
  display.setFont(u8g2_font_6x12_tr);
  display.drawStr(10, 14, "Vincular con Echo:");
  display.setFont(u8g2_font_10x20_tr);
  String spaced;
  for (size_t i = 0; i < pairCode.length(); i++) {
    spaced += pairCode[i];
    if (i == 2) spaced += ' ';
  }
  display.drawStr(18, 42, spaced.c_str());
  display.setFont(u8g2_font_5x8_tr);
  display.drawStr(4, 60, "Ajustes > Dispositivos");
  display.sendBuffer();
}

void drawMessage(const char* line1, const char* line2 = nullptr) {
  display.clearBuffer();
  display.setFont(u8g2_font_6x12_tr);
  display.drawStr(6, 28, line1);
  if (line2) display.drawStr(6, 44, line2);
  display.sendBuffer();
}

// ── I2S (INMP441) ────────────────────────────────────────────────
void setupI2S() {
  i2s_config_t config = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 8,
      .dma_buf_len = 512,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0,
  };
  i2s_pin_config_t pins = {
      .bck_io_num = PIN_I2S_SCK,
      .ws_io_num = PIN_I2S_WS,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num = PIN_I2S_SD,
  };
  i2s_driver_install(I2S_NUM_0, &config, 0, nullptr);
  i2s_set_pin(I2S_NUM_0, &pins);
}

// Lee un frame de 100 ms, lo convierte a PCM16 y lo envía. Nada se guarda.
void pumpAudio() {
  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, i2sRaw, sizeof(i2sRaw), &bytesRead, 10 / portTICK_PERIOD_MS);
  size_t samples = bytesRead / sizeof(int32_t);
  if (samples == 0) return;

  double sum = 0;
  for (size_t i = 0; i < samples; i++) {
    // INMP441: dato de 24 bits alineado a la izquierda en 32
    int16_t sample = (int16_t)(i2sRaw[i] >> 14);
    frameBuffer[i] = sample;
    double normalized = sample / 32768.0;
    sum += normalized * normalized;
  }
  audioLevel = (float)sqrt(sum / samples) * 6.0f;
  if (audioLevel > 1.0f) audioLevel = 1.0f;

  if (wsConnected && !paused) {
    audioWs.sendBIN((uint8_t*)frameBuffer, samples * sizeof(int16_t));
  }
}

// ── HTTP helpers ─────────────────────────────────────────────────
bool httpPostJson(const String& path, const String& body, JsonDocument& out,
                  bool useAuth = true) {
  HTTPClient http;
  http.begin(String(ECHO_API_BASE) + path);
  http.addHeader("Content-Type", "application/json");
  if (useAuth && deviceToken.length()) {
    http.addHeader("Authorization", "Bearer " + deviceToken);
  }
  int code = http.POST(body);
  if (code < 200 || code >= 300) {
    http.end();
    return false;
  }
  DeserializationError parseError = deserializeJson(out, http.getString());
  http.end();
  return !parseError;
}

// ── Pairing ──────────────────────────────────────────────────────
void startPairing() {
  JsonDocument response;
  JsonDocument request;
  request["kind"] = "esp32";
  request["info"]["mac"] = WiFi.macAddress();
  String body;
  serializeJson(request, body);
  if (httpPostJson("/api/devices/pair/init", body, response, false)) {
    pairCode = response["code"].as<String>();
    pairPollToken = response["poll_token"].as<String>();
    drawPairScreen();
  } else {
    mood = Mood::Error;
  }
}

void pollPairing() {
  if (pairPollToken.isEmpty()) return;
  JsonDocument response;
  JsonDocument request;
  request["poll_token"] = pairPollToken;
  String body;
  serializeJson(request, body);
  if (!httpPostJson("/api/devices/pair/poll", body, response, false)) {
    // código expirado: pedir uno nuevo
    startPairing();
    return;
  }
  if (response["status"] == "paired") {
    deviceToken = response["device_token"].as<String>();
    prefs.putString("token", deviceToken);
    pairCode = "";
    pairPollToken = "";
    mood = Mood::Done;
    doneUntil = millis() + 3000;
    drawMessage("Vinculado!", response["name"].as<const char*>());
    delay(1500);
  }
}

// ── Heartbeat ────────────────────────────────────────────────────
void heartbeat() {
  JsonDocument response;
  JsonDocument request;
  request["firmware_version"] = ECHO_FW_VERSION;
  request["state"]["wifi_rssi"] = WiFi.RSSI();
  request["state"]["status"] =
      mood == Mood::Listening ? "recording" : mood == Mood::Sleeping ? "paused" : "idle";
  String body;
  serializeJson(request, body);
  if (!httpPostJson("/api/devices/heartbeat", body, response)) {
    if (mood == Mood::Idle) mood = Mood::Error;
    return;
  }
  if (mood == Mood::Error) mood = Mood::Idle;
  // si hay una reunión activa en la organización y no estamos en una, unirse
  if (activeMeetingId.isEmpty() && !response["active_meeting"].isNull() &&
      mood == Mood::Idle) {
    activeMeetingId = response["active_meeting"]["id"].as<String>();
    connectAudioWs();
    mood = Mood::Listening;
    digitalWrite(PIN_LED, HIGH);
  }
}

// ── WebSocket de audio ───────────────────────────────────────────
void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      break;
    case WStype_DISCONNECTED:
      wsConnected = false;
      break;
    default:
      break;
  }
}

void connectAudioWs() {
  String path = "/api/devices/stream?token=" + deviceToken +
                "&meeting_id=" + activeMeetingId;
  audioWs.begin(ECHO_API_HOST, ECHO_API_PORT, path);
  audioWs.onEvent(onWsEvent);
  audioWs.setReconnectInterval(2000);
}

// ── Acciones del botón ───────────────────────────────────────────
void startMeeting() {
  JsonDocument response;
  if (httpPostJson("/api/devices/meetings", "{}", response)) {
    activeMeetingId = response["id"].as<String>();
    connectAudioWs();
    paused = false;
    mood = Mood::Listening;
    digitalWrite(PIN_LED, HIGH);
  } else {
    mood = Mood::Error;
  }
}

void finishMeeting() {
  if (activeMeetingId.isEmpty()) return;
  audioWs.sendTXT("{\"type\":\"flush\"}");
  delay(300);
  JsonDocument response;
  httpPostJson("/api/devices/meetings/" + activeMeetingId + "/finish", "{}", response);
  audioWs.disconnect();
  wsConnected = false;
  activeMeetingId = "";
  paused = false;
  digitalWrite(PIN_LED, LOW);
  mood = Mood::Thinking;
  doneUntil = millis() + 8000;  // luego pasa a Done
}

void handleButton() {
  bool down = digitalRead(PIN_BUTTON) == LOW;
  uint32_t now = millis();
  if (down && !buttonWasDown) {
    buttonDownAt = now;
  } else if (!down && buttonWasDown) {
    uint32_t held = now - buttonDownAt;
    if (held > 1500) {
      // pulsación larga: finalizar
      if (mood == Mood::Listening || mood == Mood::Sleeping) finishMeeting();
    } else if (held > 40) {
      // corta: iniciar / pausar / reanudar
      if (mood == Mood::Idle || mood == Mood::Done) {
        startMeeting();
      } else if (mood == Mood::Listening) {
        paused = true;
        mood = Mood::Sleeping;
        digitalWrite(PIN_LED, LOW);
      } else if (mood == Mood::Sleeping) {
        paused = false;
        mood = Mood::Listening;
        digitalWrite(PIN_LED, HIGH);
      }
    }
  }
  buttonWasDown = down;
}

// ── Setup / Loop ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  display.begin();
  drawMessage("Echo Device", "iniciando...");

  prefs.begin("echo", false);
  deviceToken = prefs.getString("token", "");

  // WiFi: credenciales compiladas, o las últimas guardadas en NVS.
  // ⚠️ NO hay portal de configuración. Si WIFI_SSID está vacío y el equipo no
  // tiene credenciales previas en NVS, no hay forma de configurarlo sin
  // volver a flashearlo. Provisioning (SoftAP/BLE/SmartConfig) está pendiente.
  if (strlen(WIFI_SSID) > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  } else {
    WiFi.begin();  // intenta las últimas credenciales guardadas en NVS
  }
  drawMessage("Conectando WiFi...");
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(250);
  }
  if (WiFi.status() != WL_CONNECTED) {
    mood = Mood::Error;
    drawMessage("Sin WiFi", "revisa echo_config.h");
  }

  setupI2S();

  if (deviceToken.isEmpty() && WiFi.status() == WL_CONNECTED) {
    startPairing();
  }
}

void loop() {
  handleButton();
  audioWs.loop();

  if (mood == Mood::Listening && !paused) {
    pumpAudio();
  }

  uint32_t now = millis();

  // pairing pendiente: refrescar pantalla y poll cada 3 s
  if (!pairCode.isEmpty()) {
    if (now - lastPairPoll > 3000) {
      lastPairPoll = now;
      pollPairing();
      if (!pairCode.isEmpty()) drawPairScreen();
    }
    return;
  }

  // thinking → done
  if (mood == Mood::Thinking && doneUntil && now > doneUntil) {
    mood = Mood::Done;
    doneUntil = now + 6000;
  } else if (mood == Mood::Done && doneUntil && now > doneUntil) {
    mood = Mood::Idle;
    doneUntil = 0;
  }

  if (now - lastHeartbeat > 15000 && deviceToken.length()) {
    lastHeartbeat = now;
    heartbeat();
  }

  if (now - lastFaceDraw > 90) {
    lastFaceDraw = now;
    drawFace();
  }
}
