#pragma once

// ── Configuración de Echo Device ─────────────────────────────────
// Completá WiFi y servidor antes de flashear. NO hay portal de configuración:
// estos valores son la única forma de configurar el equipo.

#define ECHO_FW_VERSION "1.0.0"

// WiFi — OBLIGATORIO.
// ⚠️ NO hay portal de configuración ni AP "Echo-Setup". No existe SoftAP,
// ni DNSServer, ni WebServer en este firmware: `main.cpp` hace `WiFi.begin()`
// y nada más. Si dejás WIFI_SSID vacío, el equipo intenta reconectarse a las
// últimas credenciales guardadas en NVS; si no hay ninguna (equipo recién
// flasheado), queda en pantalla de error SIN NINGUNA FORMA DE CONFIGURARLO
// salvo volver a flashearlo. Completalo.
#define WIFI_SSID ""
#define WIFI_PASS ""

// Servidor de Echo — sin barra final.
// ⚠️ SOLO HTTP/WS EN TEXTO PLANO. Este firmware no habla TLS: no usa
// WiFiClientSecure ni wss://. No puede conectarse al deploy de producción
// (que es HTTPS); apuntalo a un Echo API alcanzable por HTTP plano en la LAN,
// o al Echo Bridge de una PC de la sala.
#define ECHO_API_BASE "http://192.168.1.100:8787"
// Host/puerto para el WebSocket (mismo host del API)
#define ECHO_API_HOST "192.168.1.100"
#define ECHO_API_PORT 8787

// ── Pines ────────────────────────────────────────────────────────
// I2S — INMP441
#define PIN_I2S_SCK 4    // BCLK
#define PIN_I2S_WS 5     // LRCLK
#define PIN_I2S_SD 6     // DOUT del micrófono

// OLED SSD1306 (I2C)
#define PIN_OLED_SDA 8
#define PIN_OLED_SCL 9

// Botón (a GND, con pull-up interno)
#define PIN_BUTTON 2
// LED de estado (rojo = grabando)
#define PIN_LED 3

// Audio
#define SAMPLE_RATE 16000
#define FRAME_SAMPLES 1600  // 100 ms por frame
