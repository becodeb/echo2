# Echo Device (ESP32)

Compañero físico de reuniones: una carita que escucha. Firmware en
`firmware/esp32` (PlatformIO + Arduino, ESP32-S3).

> ⚠️ El firmware está escrito como base funcional pero **no fue compilado ni
> probado sobre hardware** en este repositorio (la máquina de desarrollo no
> tiene el toolchain de PlatformIO). Validalo con `pio run` antes de flashear.

## Hardware de referencia

| Componente | Modelo | Pines (echo_config.h) |
|---|---|---|
| MCU | ESP32-S3 DevKitC-1 | — |
| Micrófono | INMP441 (I2S MEMS) | SCK 4 · WS 5 · SD 6 |
| Pantalla | OLED SSD1306 128×64 I2C | SDA 8 · SCL 9 |
| Botón | pulsador a GND | GPIO 2 (pull-up interno) |
| LED grabación | LED + resistencia | GPIO 3 |

Cableado INMP441: `L/R → GND` (canal izquierdo), `VDD → 3V3`, `GND → GND`.

## La cara

| Estado | Cara | Cuándo |
|---|---|---|
| idle | 🙂 ojos abiertos, parpadeo ocasional | listo |
| listening | 👂 ojos que crecen con el volumen + «● GRABANDO» | reunión en vivo |
| thinking | ··· puntos animados | procesando al finalizar |
| sleeping | ─ ─ + `z Z z` | pausado |
| done | ^ ^ y sonrisa | acta lista |
| error | x x | sin WiFi / sin vínculo |

El indicador **GRABANDO** en pantalla + LED rojo son obligatorios siempre que
haya captura activa (nunca grabación oculta).

## Botón

- **Corta**: iniciar reunión / pausar / reanudar.
- **Larga (>1.5 s)**: finalizar (dispara el pipeline y pasa a thinking→done).

## Onboarding (pairing)

1. Flasheá con tu WiFi y servidor en `include/echo_config.h`.
2. Al arrancar sin token, el equipo pide un código al servidor y muestra
   `CODE ######` en pantalla (expira a los 10 min y se renueva).
3. En Echo web: **Ajustes → Dispositivos → Vincular** → ingresá el código.
4. El dispositivo recibe su token definitivo por polling y lo guarda en NVS
   (Preferences). Desde ahí: heartbeat cada 15 s (RSSI, firmware, estado) y
   aparece 🟢 Online en la página de dispositivos.

Si la organización inicia una reunión desde la web, el dispositivo se une
solo (lo ve por heartbeat) y empieza a transmitir.

## Audio

I2S 16 kHz, frames de 100 ms convertidos a PCM16 y enviados por WebSocket a
`/api/devices/stream` (token de dispositivo + meeting_id). **Nada se almacena
en el ESP32**. El servidor aplica la misma política del modo cloud (RAM →
STT → descarte). Para que el audio no salga de la LAN, apuntá
`ECHO_API_HOST` al Echo Bridge de una PC de la sala (misma interfaz WS).

## OTA (preparado, no implementado)

El heartbeat ya devuelve `available_version` y la tabla `devices` distingue
`firmware_version` / `available_version`. Falta: servidor de binarios +
`Update.h` en el firmware. Diseño previsto: el heartbeat indica una URL
firmada y el equipo actualiza fuera de reuniones.

## Compilar y flashear

```bash
cd firmware/esp32
pio run                      # compilar
pio run -t upload            # flashear
pio device monitor           # logs (115200)
```
