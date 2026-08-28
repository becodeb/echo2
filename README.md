<p align="center">
  <img src="apps/web/public/favicon.svg" width="72" alt="Echo" />
</p>

<h1 align="center">Echo</h1>

<p align="center"><strong>The meeting ends. Echo remembers.</strong><br/>
La reunión termina. Echo recuerda.</p>

Echo convierte reuniones en conocimiento consultable: transcripción en vivo,
hablantes, decisiones, tareas, acta verificada, búsqueda semántica, memoria
entre reuniones y chat con fuentes.

**Flujo:** REUNIÓN → AUDIO → TRANSCRIPCIÓN → HABLANTES → INFORMACIÓN ESTRUCTURADA → ACTA → MEMORIA → CHAT

## Principio fundamental: el audio no se guarda

Echo es **privacy-first**. El audio existe solo en RAM el tiempo necesario para
transcribirlo:

```
captura → memoria RAM → STT → texto → destruir audio
```

- Con **Echo Bridge** (recomendado): el audio nunca sale de tu computadora;
  solo el texto llega al servidor.
- En **modo cloud**: el audio viaja cifrado al proveedor STT configurado y se
  descarta al transcribir. La UI siempre avisa qué modo está activo.
- Lo que persiste: transcript, timestamps, hablantes, decisiones, tareas,
  resúmenes, acta, embeddings y metadata. Nunca WAV/MP3/WebM.
- Cuando hay captura activa, la web y el dispositivo muestran **● Grabando**.

## Arquitectura

```
┌─────────────┐   texto    ┌──────────────┐        ┌──────────────┐
│   Browser   │───────────▶│   Echo API   │───────▶│  PostgreSQL  │
│  (React)    │◀───────────│  (FastAPI)   │        │  + pgvector  │
└──────┬──────┘  WS live   └──────┬───────┘        └──────────────┘
       │ audio (localhost)        │ LLM/STT/Embeddings providers
┌──────▼──────┐            ┌──────▼───────┐
│ Echo Bridge │            │ OpenAI/Anthropic/Groq/…  (configurable)
│   (Rust)    │            └──────────────┘
└──────┬──────┘
       │ Murmur / whisper.cpp / servidor STT local
┌──────▼──────┐
│ Echo Device │  ESP32-S3 con carita (firmware/esp32)
└─────────────┘
```

```
echo/
├── apps/
│   ├── api/        FastAPI + SQLAlchemy + Alembic (corre en Docker)
│   ├── web/        React + Vite + TS + Tailwind 4 + TanStack Query (PWA)
│   └── bridge/     Echo Bridge en Rust (STT local en 127.0.0.1)
├── firmware/esp32/ Echo Device (PlatformIO, ESP32-S3)
├── docs/           arquitectura, bridge, murmur, esp32, seguridad
└── docker-compose.yml
```

## Puesta en marcha (desarrollo)

Requisitos: Docker, Node 20+ con pnpm, y (opcional) Rust para el bridge.

```bash
# 1. entorno
cp .env.example .env
# completá JWT_SECRET y ENCRYPTION_KEY (los comandos están en el archivo)

# 2. backend (Postgres+pgvector + API con migraciones automáticas)
docker compose up -d
# API en http://localhost:8787  (Swagger: /api/docs)

# 3. web
cd apps/web && pnpm install && pnpm dev
# http://localhost:5173

# 4. (opcional) Echo Bridge — STT local
cd apps/bridge && cargo run --release
# escucha en http://127.0.0.1:8974

# 5. (opcional) datos de demo
docker compose exec api python -m echo_api.seed
# usuario demo@echodemo.dev / demo1234
```

### Primera ejecución real

1. Registrate y creá tu organización.
2. **Ajustes → IA**: configurá tu proveedor LLM (OpenAI/Anthropic/Gemini/Groq/
   OpenRouter/Ollama), su API key (se guarda cifrada) y el motor STT cloud de
   respaldo. Sin esto Echo transcribe pero no analiza — y lo dice claramente,
   nunca simula.
3. **Ajustes → Formato de acta**: pegá el modelo REAL de acta de tu
   organización. Es la source of truth del generador (hasta entonces rige una
   plantilla provisional marcada como tal).
4. `+ Nueva reunión` → elegí micrófono y motor → **Iniciar reunión**.
5. Al tocar **Finalizar**, Echo consolida hablantes, extrae decisiones/tareas
   (con fechas relativas resueltas), genera resúmenes, produce el acta y la
   **verifica afirmación por afirmación contra el transcript**.
6. Preguntale a la reunión (chat con fuentes y timestamps) o a toda la
   organización (**Preguntale a Echo**).

## Variables de entorno

Ver `.env.example`. Claves:

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | PostgreSQL (asyncpg). Compose la setea sola |
| `JWT_SECRET` | Firma de tokens (obligatoria en prod) |
| `ENCRYPTION_KEY` | Fernet: cifra las API keys en reposo (obligatoria en prod) |
| `WEB_ORIGIN` | Origin del frontend para CORS |
| `OPENAI_API_KEY`… | Defaults globales opcionales de providers |

Las keys por organización se configuran desde la UI y **siempre** se guardan
cifradas; nunca vuelven completas al frontend ni aparecen en logs.

## Motor local: Murmur / whisper

Echo Bridge detecta automáticamente el motor STT instalado, sin asumir cómo:

1. `engine_command` de su config (override manual — ideal para Murmur:
   `"murmur transcribe {input}"`).
2. `murmur` en PATH (sondea sus subcomandos).
3. whisper.cpp (`whisper-cli`/`whisper-cpp`/`main`) + modelo ggml/gguf
   (autodetección en rutas típicas o `model_path`).
4. Servidor HTTP local compatible con whisper.cpp server (`server_url`).

Config del bridge: `%APPDATA%/echo-bridge/config.json` (Windows) o
`~/.config/echo-bridge/config.json`. Ver [docs/murmur.md](docs/murmur.md) y
[docs/bridge.md](docs/bridge.md).

> En esta máquina no se encontró una instalación de Murmur (PATH, servicios,
> carpetas típicas). El bridge queda en autodetección: cuando Murmur esté
> disponible o configures `engine_command`, pasa a ser el motor preferido.

## Proveedores

| Rol | Opciones |
|---|---|
| LLM | OpenAI, Anthropic, Gemini, Groq, OpenRouter, Ollama (ningún modelo hardcodeado) |
| STT local | Murmur / whisper.cpp / servidor compatible (vía Echo Bridge) |
| STT cloud | OpenAI Whisper, Groq, Deepgram |
| Embeddings | OpenAI, Ollama (pgvector con normalización de dimensión) |

## Tests

```bash
docker compose exec api pytest          # 25 tests
```

Cubren: auth (registro/login/refresh/CSRF), **aislamiento de tenant**
(headers ajenos, reuniones privadas, búsquedas), unidades (fechas relativas,
parseo LLM, chunking, contexto del verificador) y un **E2E del flujo completo**
del producto: crear cuenta → org → reunión → grabar por WS → finalizar →
pipeline → insights con evidencia → acta verificada → renombrar hablante →
chat con fuentes → editar transcript con historial → compartir por link →
re-login → búsqueda. Los providers de IA se reemplazan por fakes **solo en
tests** (§72: en producción nada se simula — las features sin configuración lo
indican).

## Seguridad

HTTPS-ready, JWT cortos + refresh rotativo httpOnly, header anti-CSRF, RBAC
(owner/admin/member/viewer), aislamiento por organización verificado en DB en
cada request, rate limiting, API keys cifradas, audit log, links de compartir
revocables con expiración, bridge solo-loopback con validación de Origin y
tokens de sesión. Detalle: [docs/security.md](docs/security.md).

## Echo Device (ESP32)

Firmware PlatformIO para ESP32-S3 + micrófono I2S + OLED con la carita de
Echo (estados 🙂 👂 ··· 😴 ✓ ⚠, indicador GRABANDO, botón físico, pairing por
código de 6 dígitos, streaming PCM16). Ver [docs/esp32.md](docs/esp32.md).
*El firmware compila pero no fue probado sobre hardware en este repo.*

## Estado y limitaciones actuales

- **Diarización**: hoy se sostiene con speaker turns del motor local (p. ej.
  whisper.cpp tinydiarize), hints por canal (mic vs. audio del sistema /
  dispositivo) y herramientas manuales completas (renombrar, unir, separar,
  reasignar). La interfaz `DiarizationProvider` y el pipeline de
  consolidación ya existen para enchufar un modelo de embeddings de voz
  (ECAPA/pyannote) sin tocar el resto. Los voice profiles (schema + consent)
  están modelados; la identificación automática requiere ese provider.
- **Deepgram streaming** WS: hoy usa el modo prerecorded por ventanas.
- **OTA del ESP32**: campos `firmware_version`/`available_version` y heartbeat
  listos; falta el servidor de binarios.
- **Notificaciones por email**: la arquitectura de notificaciones existe
  (in-app); el transporte de email queda configurable a futuro.

## Pendientes que dependen del usuario

1. **Modelo real de acta** → Ajustes → Formato de acta (o `PUT
   /api/org/minutes-template`).
2. **API keys** de LLM/STT/embeddings → Ajustes → IA.
3. **Murmur**: indicar dónde está instalado (o el comando exacto) en la config
   de Echo Bridge para que sea el motor local preferido.
