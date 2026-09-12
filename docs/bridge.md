# Echo Bridge

Servicio local que conecta el navegador con tu motor STT (Murmur, whisper.cpp
o un servidor compatible). **El audio nunca sale de tu computadora**: entra
por WebSocket desde el navegador, se transcribe localmente y solo el texto
vuelve.

## Instalación

```bash
cd apps/bridge
cargo build --release
# binario: target/release/echo-bridge(.exe)  (~4 MB)
./target/release/echo-bridge
```

Escucha **solo en 127.0.0.1:8974** (nunca en la red). La web lo detecta sola
y muestra:

- 🟢 Motor local conectado (nombre del motor)
- 🟡 Bridge corriendo pero sin motor STT
- ⚪ Echo Bridge no encontrado → se ofrece el modo cloud

### ⚠️ Si usás Echo desde el dominio de producción, agregá ese origin

Los `allowed_origins` por defecto (`apps/bridge/src/main.rs`, `default_origins`)
son exactamente tres, todos locales:

```
http://localhost:5173    http://127.0.0.1:5173    http://localhost:4173
```

**El dominio de producción no está en esa lista.** Si abrís Echo desde el sitio
deployado, el `POST /session` del bridge valida el header `Origin`, no lo
encuentra en la allowlist y responde **403**. El bridge está corriendo, el
motor está instalado, y aun así la web te va a ofrecer el modo cloud como si no
hubiera bridge.

Esto no es un bug: la allowlist es justamente lo que impide que una página
cualquiera use tu micrófono y tu motor local. Pero hay que completarla a mano,
una vez por máquina:

```jsonc
// %APPDATA%\echo-bridge\config.json  ·  ~/.config/echo-bridge/config.json
{
  "allowed_origins": [
    "http://localhost:5173",
    "https://echo.tu-dominio.com"   // ← agregá el tuyo
  ]
}
```

Reiniciá el bridge después de editarlo. Poné el origin exacto (esquema, host y
puerto): `https://echo.tu-dominio.com` y `https://www.echo.tu-dominio.com` son
orígenes distintos para esta validación.

## Configuración

Primera ejecución crea `config.json` en:
- Windows: `%APPDATA%\echo-bridge\config.json`
- Linux/macOS: `~/.config/echo-bridge/config.json`

```json
{
  "port": 8974,
  "allowed_origins": ["http://localhost:5173"],
  "engine_command": null,
  "model_path": null,
  "server_url": null,
  "language": "es"
}
```

| Campo | Uso |
|---|---|
| `engine_command` | Override manual del motor. Placeholders: `{input}` (wav), `{lang}`, `{output}`. Ej: `"murmur transcribe {input}"` |
| `model_path` | Modelo ggml/gguf para whisper.cpp |
| `server_url` | Servidor HTTP tipo whisper.cpp server (`/inference`) |
| `allowed_origins` | Orígenes web que pueden emparejarse (agregar el dominio de producción) |

## Detección del motor (orden)

1. `engine_command` (si está seteado).
2. **`murmur` en PATH** — se sondea `murmur --help` buscando subcomandos
   (`transcribe`, `stt`, `recognize`, `run`) o soporte de archivo directo.
3. **whisper.cpp**: `whisper-cli` / `whisper-cpp` / `whisper` / `main` en
   PATH + modelo en `model_path` o rutas típicas (`~/whisper.cpp/models`,
   `~/.cache/whisper`, `%LOCALAPPDATA%/whisper/models`…). Se invoca con
   `-oj` (JSON con timestamps por segmento). Con un modelo *tinydiarize*
   (`ggml-small.en-tdrz.bin`) los `[SPEAKER_TURN]` se convierten en hints de
   hablante.
4. **Servidor HTTP local** compatible whisper.cpp server (`server_url`, o
   autodetección en `http://127.0.0.1:8080`).

Sin motor: `/health` lo informa (`engine.available=false` + motivo) y Echo
sigue en modo cloud. Nada se simula.

## Seguridad

- Bind exclusivo a loopback; nunca acepta conexiones externas.
- `POST /session` valida el header `Origin` contra `allowed_origins` y emite
  un token de sesión efímero (12 h, en memoria) — una página web arbitraria
  no puede usar tu micrófono ni tu motor.
- El WS `/stt` exige ese token. Rate limit en el pairing.
- CORS restringido a los orígenes permitidos.

## Pipeline interno

```
PCM16 16k → VAD por energía (histéresis 700 ms) → utterance
   → (CLI: WAV temporal efímero | HTTP: multipart en memoria)
   → segmentos {texto, start_ms, end_ms, speaker?}
   → {type:"final"|"partial"} al navegador
```

Utterances de máx. 10 s (se fuerza ventana con `partial`); el buffer se vacía
en cada transcripción. `{"type":"flush"}` fuerza el cierre (pausa/fin de
reunión).
