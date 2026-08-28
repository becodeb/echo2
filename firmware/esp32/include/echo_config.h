#pragma once

// ── Configuración de Echo Device ─────────────────────────────────
// Completá WiFi y servidor antes de flashear (o dejá WIFI_SSID vacío para
// que el dispositivo levante un portal de configuración propio).

#define ECHO_FW_VERSION "1.0.0"

// WiFi (vacío => portal de configuración en el AP "Echo-Setup")
#define WIFI_SSID ""
#define WIFI_PASS ""

// Servidor de Echo (API cloud) — sin barra final
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
