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

## Qué es Echo hoy: dos capas que conviven

Esto es lo primero que hay que entender, porque el producto creció y no lo
dijo. Echo tiene **dos vocabularios funcionando al mismo tiempo**, y los dos
están navegables en el menú:

**La capa institucional** — para escuelas especiales, equipos de orientación
escolar y centros terapéuticos. El sujeto de la reunión no es un proyecto: es
una **familia**. Cada reunión se hace *con* una familia, por un **motivo** de
una lista que la institución define, con una **gravedad** (semáforo verde /
amarillo / rojo), y se registra **quién vino, tutor por tutor**. Encima de eso
hay **reportes** agregados y una integración con **Google Drive** que deja el
acta en la carpeta de cada familia.

**La capa corporativa original** — Proyectos, Personas, Mi trabajo y
Preguntale a Echo. Sigue viva, sin gate de rol ni feature flag, con sus
endpoints funcionando.

**No hay migración ni reemplazo entre una y otra.** Se ve en el modelo: una
reunión lleva `family_id`, `reason_id`, `severity` y `audience` como columnas
propias, **todas nullable** — el comentario junto a las tres primeras lo dice
así: *«una reunión se puede grabar primero y clasificar después, y no toda
reunión es con una familia»*. El vínculo con proyectos, en cambio, no es una
columna: va por una tabla puente aparte (`project_meetings`). Las dos
clasificaciones son opcionales e independientes, y nada en la UI te empuja
hacia una capa.

En la práctica cada organización usa la que le sirve y **ignora la otra**, que
le queda como menú muerto. Es una tensión real del producto, no una fase de
transición: si vas a trabajar acá, elegí a conciencia en qué capa cae lo que
estás construyendo.

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

### Si vas a usar el vertical institucional

Antes de la primera reunión con una familia conviene dejar cargado esto:

1. **Ajustes → Motivos de reunión**: la lista es cerrada y la define cada
   organización, así que arranca vacía. Sin motivos no se puede clasificar.
2. **Familias**: cargá la familia y sus integrantes, marcando quiénes son
   responsables (`is_guardian`) — son los únicos que cuentan para «¿estuvieron
   todos?».
3. **Familias → Profesionales**: el catálogo es de la organización. Cargá cada
   profesional una sola vez y vinculalo a las familias que acompaña.
4. *(Opcional)* **Ajustes → Google Drive**: conectá la cuenta para que el acta
   aprobada se suba sola a la carpeta de cada familia.
5. Al terminar la reunión, clasificala: familia, motivo, gravedad, audiencia y
   quién vino. Recién ahí aparece en **Reportes**.

Para el superadmin: `SUPERADMIN_EMAILS` en el `.env` y reiniciar la API. No se
otorga desde la interfaz, por diseño.

## El vocabulario institucional

Todo esto vive en `apps/api/echo_api/models/families.py`, que tiene los
docstrings más explicativos del repo. Si vas a tocar el vertical, leelo antes.

| Concepto | Qué es |
|---|---|
| **Familia** | El sujeto de la reunión. Tiene nombre, `reference` (legajo o matrícula, «como lo llame la institución») y opcionalmente el link a su carpeta de Drive |
| **Integrante** | Madre, padre, tutor, estudiante u otro. `tutor` cubre abuelos, tíos y cualquier adulto responsable |
| **Profesional** | Terapeuta, acompañante, docente externo. **Cuelga de la organización, no de la familia** |
| **Motivo** | Lista cerrada que define cada organización. No es texto libre |
| **Gravedad** | Semáforo `verde` / `amarillo` / `rojo` |
| **Audiencia** | Con quién fue: `familia`, `profesionales`, `mixta`, `docentes`, `interna` |
| **Asistencia** | Tabla, una fila por integrante y por reunión |

### Las decisiones de diseño, y por qué

No las inventamos acá: están argumentadas en el código y vale la pena
entenderlas antes de «simplificar» alguna.

**La asistencia es una tabla, no un booleano en la reunión.** Textual del
modelo: *«la pregunta real no es "¿vinieron todos?" sino "¿quién faltó, y
falta seguido?". Con un booleano esa segunda pregunta no se puede contestar
nunca más.»* De ahí sale el ranking de ausentes del reporte.

**Los motivos se desactivan, no se borran** (`is_active`). *«Las reuniones
viejas tienen que seguir mostrando el motivo con el que se cargaron.»* Por eso
no existe un `DELETE` de motivo en la API. Lo mismo con familias y
profesionales: baja lógica, porque el histórico no se puede quedar sin el
nombre.

**El profesional vive a nivel organización.** *«El mismo profesional suele
acompañar a varias [familias]. Cargarlo una vez es lo que permite después
preguntar "¿a cuántas familias ve?".»*

**La gravedad es un color y no un número.** *«Para que dos personas puntúen
igual: "amarillo" admite menos interpretación que "3 sobre 5".»*

**La asistencia de profesionales es una tabla aparte de la familiar**, a
propósito: *«"vinieron todos los responsables" es una pregunta sobre la
familia, y mezclar profesionales ahí adentro la contestaría mal.»* Y son
asimétricas: a un integrante que no vino se lo marca **ausente** (queda el
registro de la falta), a un profesional que no vino simplemente **no se lo
registra** — no participó, no es una ausencia que haya que contar.

**«No se sabe» no es «no vinieron».** `all_guardians_present` es tri-estado
(`true` / `false` / `null`). Sin ningún registro de asistencia la respuesta
correcta es «no se sabe»: *«son cosas distintas en un reporte.»*

**Sólo los `is_guardian` cuentan para «¿estuvieron todos?»**. Un hermano mayor
puede figurar en la familia sin que su ausencia cuente.

### Clasificar una reunión

Va todo junto en un solo `PUT /api/meetings/{id}/classification` — familia,
motivo, gravedad, audiencia y asistencias — *«porque en la práctica se
completa de una sola sentada, al terminar la reunión»*. Requiere rol `editor`
o superior sobre la reunión.

Dos detalles que importan al integrar: hay que mandar la **lista completa** de
presentes, porque lo que no viene se marca como ausente; y si se cambia la
familia de una reunión ya clasificada, **se borran las asistencias previas**
(pertenecen a la familia anterior, dejarlas mezclaría integrantes de dos
familias en la misma reunión).

### Reportes

Un solo endpoint, `GET /api/reports/overview?date_from=&date_to=` (por defecto
los últimos 12 meses), que alimenta la página **Reportes**. Devuelve JSON:
totales (incluido cuántas reuniones quedaron sin clasificar), serie mensual,
por familia (con desglose del semáforo y última reunión), por motivo, por
gravedad, y asistencia (`complete` / `incomplete` / `unknown` + **top 10 de
ausentes**).

Lo ve cualquier miembro, incluso `viewer`. **No exporta CSV ni PDF**: sólo
JSON, y la página lo dibuja con barras hechas a mano en divs. La exportación a
MD/TXT/DOCX/PDF existe pero es de **actas y transcripts**, no de reportes.

Nota de implementación, textual del código: la agregación se hace **en Python,
no con GROUP BYs**, a propósito — *«el volumen acá es institucional (cientos, a
lo sumo miles de reuniones por año), y la pregunta de asistencia … en SQL puro
sale ilegible. Si algún día una organización llega a decenas de miles de
reuniones, esto se reescribe con agregados; hoy no paga la complejidad.»*

## Superadmin

Es un rol **de la instalación, no de una organización**: un superadmin no es
miembro de las orgs que administra, así que el panel no usa el header
`X-Organization-Id`.

Se otorga **sólo por la variable de entorno `SUPERADMIN_EMAILS`** (emails
separados por coma) y se sincroniza contra la DB **al arrancar la API**.
Deliberadamente fuera de la app: *«nadie se asciende a sí mismo desde la UI, se
cambia acá y se reinicia»*. Quien sale de la lista pierde el privilegio en el
próximo arranque; si todavía no se registró, queda marcado cuando lo haga. Si
la lista está vacía **no se revoca a nadie**.

Qué puede hacer, y nada más que eso: ver todas las organizaciones con sus
conteos, configurarles el proveedor de IA, y fijar el **default de IA de toda
la instalación**. Incluye un botón que **le pega de verdad al proveedor** —
*«es la diferencia entre "configuré una key" y "la key funciona". Una key
válida sobre una cuenta sin saldo pasa cualquier validación de formato y falla
recién cuando alguien intenta generar un acta.»*

Qué **no** puede: crear o borrar organizaciones, ver reuniones, transcripts o
actas, gestionar miembros, ni leer una API key en claro (siempre enmascarada).
Los cambios quedan en el audit log **de la organización afectada**, con el
nombre de quien los hizo.

Para quien no es superadmin el panel devuelve **404, no 403**: no existe.

## Google Login y Google Drive

Son dos integraciones distintas que comparten `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET`. Sin esas variables las dos se apagan solas y la UI no
ofrece el botón.

**Login** (`/api/auth/google/*`). Scope `openid email profile`, `access_type=online`.
Si el email ya existe como cuenta con contraseña, **se vincula** a la
preexistente. Si no existe, **crea el usuario sin contraseña**. Exige
`email_verified`: Google lo marca en falso en dominios delegados sin verificar
y ahí no se puede confiar en el email para unificar cuentas.

Ojo con esto: **entrar con Google no te mete en ninguna organización.** El
usuario queda suelto y tiene que crear una org o aceptar una invitación, igual
que en el registro normal.

**Drive** (`/api/org/drive/*`, Ajustes → Google Drive). Sube el acta aprobada
como **DOCX** a una carpeta madre por organización, con una subcarpeta por
familia que se crea sola. Requiere rol `admin`.

El scope es **`drive.file`, el mínimo posible**, y no es configurable a
propósito: *«Echo solo ve y toca lo que él mismo creó, así que no puede leer el
Drive de la institución aunque quisiera. El permiso amplio (`drive`) daría
acceso a todo y exige revisión de Google; no vale la pena para lo único que
hace falta acá, que es escribir actas.»* La constante vive en el código y no en
la config porque *«pedir más cambiaría el trato con el usuario y tiene que ser
una decisión de código»*.

Consecuencia práctica del scope mínimo: si alguien pega a mano en `drive_url`
una carpeta que **no creó Echo**, Echo no va a poder escribir ahí. `drive.file`
no da permiso sobre carpetas ajenas.

Se persiste un solo **refresh token por organización, cifrado**. Desconectar
borra el token pero **no toca los archivos**: ya son de la institución.

## Cómo se elige el modelo de IA (cadena de precedencia)

Es la parte más confusa de configurar, así que acá está completa.
`resolve_llm` (`services/ai_settings.py`) baja por cuatro niveles y **gana el
primero que resuelve**:

| # | Nivel | Dónde se configura |
|---|---|---|
| 1 | **Organización** | Ajustes → IA (key cifrada en DB) |
| 2 | **Servidor** | `/admin` → default de la instalación (superadmin) |
| 3 | **Entorno explícito** | `DEFAULT_LLM_PROVIDER` + `DEFAULT_LLM_MODEL` |
| 4 | **Autodetección** | primera key presente: anthropic → openai → groq → openrouter → orcarouter → gmi → ollama |

Si ninguno resuelve, no hay IA: las etapas se saltean y la UI lo dice. Nada se
simula.

El nivel 2 va **antes** que el entorno a propósito: es lo que permite cambiar
la key sin redeploy.

Dos comportamientos que sorprenden y conviene saber:

- **Elegir provider sin cargar key no salta de nivel por sí solo.** Echo busca
  la key de *ese* provider en el entorno; recién si no hay ninguna baja al
  nivel siguiente. Es decir: el provider que elegiste se respeta aunque la key
  venga del `.env`. (`ollama` es la excepción, no necesita key.)
- **`DEFAULT_LLM_PROVIDER` vacío significa autodetectar.** Explicitarlo evita
  que cargar una key para STT —por ejemplo la de OpenAI— te cambie de golpe el
  modelo del chat.

Y una asimetría real: **sólo el LLM tiene el nivel 2.** `resolve_stt` y
`resolve_embeddings` tienen dos niveles (organización → entorno) y **no miran
el default del servidor**. El superadmin gobierna el LLM y nada más.

## Variables de entorno

Ver `.env.example`. Claves:

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | PostgreSQL (asyncpg). Compose la setea sola |
| `JWT_SECRET` | Firma de tokens (obligatoria en prod) |
| `ENCRYPTION_KEY` | Fernet: cifra API keys y el refresh token de Drive en reposo (obligatoria en prod) |
| `WEB_ORIGIN` | Origin del frontend para CORS |
| `API_PUBLIC_URL` | URL pública del API. Con esto se arma el callback de Google |
| `SUPERADMIN_EMAILS` | Emails separados por coma. **Única forma de otorgar superadmin**; se sincroniza al arrancar |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Habilitan Google Login y Drive. Sin las dos, ambas se apagan |
| `GOOGLE_REDIRECT_URI` | Opcional: pisa el callback derivado de `API_PUBLIC_URL` |
| `DEFAULT_LLM_PROVIDER` / `DEFAULT_LLM_MODEL` | Nivel 3 de la cadena de precedencia. Vacío = autodetectar |
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

> **En esta máquina el motor local ya está instalado y verificado**: el motor
> de Murmur (Parakeet TDT 0.6B v3 multilingüe vía sherpa-onnx) vive en
> `%LOCALAPPDATA%\echo-bridge\` y el bridge lo autodetecta. Transcripción
> en español e inglés, offline, ~16× tiempo real.

## Proveedores

| Rol | Opciones |
|---|---|
| LLM | OpenAI, Anthropic, Gemini, Groq, OpenRouter, Ollama (ningún modelo hardcodeado) |
| STT local | **Parakeet/sherpa-onnx (motor de Murmur — instalado)**, whisper.cpp, servidor compatible (vía Echo Bridge) |
| STT cloud | OpenAI Whisper, Groq, Deepgram |
| Embeddings | OpenAI, Ollama (pgvector con normalización de dimensión) |

## Tests

```bash
docker compose exec api pytest -q       # la suite te dice cuántos son
```

No ponemos el número acá a propósito: una cifra en el README envejece al
siguiente commit y nadie la actualiza, y entonces el README miente. La suite
es la fuente de verdad; `pytest -q` la imprime en la última línea.

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
*El firmware está escrito como base funcional; no fue compilado ni probado sobre hardware en este repo.*

Dos límites que hay que saber **antes de comprar el hardware**:

- **No habla TLS.** Usa `HTTPClient` sobre `http://` y WebSocket sin SSL; no
  hay `WiFiClientSecure` en el firmware. **No puede conectarse a un Echo
  deployado detrás de HTTPS.** Sirve contra un API por HTTP plano en la LAN o
  contra el Echo Bridge de una PC de la sala.
- **No hay portal de configuración WiFi.** El header prometía un AP
  `Echo-Setup` que nunca se implementó (no hay `SoftAP`, ni `DNSServer`, ni
  `WebServer`): el firmware hace `WiFi.begin()` y nada más. **Flashear con
  `WIFI_SSID` vacío deja el equipo inutilizable** — sin credenciales previas en
  NVS no hay forma de configurarlo salvo volver a flashearlo por USB.

## Estado y limitaciones actuales

- **Diarización**: hoy se sostiene con speaker turns del motor local (p. ej.
  whisper.cpp tinydiarize), hints por canal (mic vs. audio del sistema /
  dispositivo) y herramientas manuales completas (renombrar, unir, separar,
  reasignar).
  Que quede claro qué **no** hay, porque este README afirmaba lo contrario:
  **no existe ninguna interfaz `DiarizationProvider`** ni ningún punto de
  extensión preparado. Enchufar un modelo de embeddings de voz (ECAPA/
  pyannote) es diseño desde cero, no un plug-in.
- **Voice profiles: schema sin implementación.** El modelo `SpeakerProfile`
  existe con su columna de embedding y su `consent_at`, y la migración crea la
  tabla, pero **ningún código la lee ni la escribe**: no hay endpoint para dar
  de alta un perfil ni nada que calcule ese embedding. Es una tabla vacía.
  Echo **no** almacena biometría de voz hoy.
- **`diarization_provider` es config muerta.** Se puede setear en Ajustes → IA
  y se persiste en la DB, pero **ningún consumidor la lee**. Un admin la
  cambia y no pasa absolutamente nada. Hay que cablearla o borrarla.
- **Deepgram streaming** WS: hoy usa el modo prerecorded por ventanas.
- **OTA del ESP32**: campos `firmware_version`/`available_version` y heartbeat
  listos; falta el servidor de binarios.
- **Notificaciones por email**: la arquitectura de notificaciones existe
  (in-app); el transporte de email queda configurable a futuro.

### Backend terminado al que no se llega desde la web

Estos endpoints están completos, testeados y montados en la API, pero **no
tienen ninguna entrada en la interfaz**. Un usuario no puede alcanzarlos. O se
les da UI o se borran; dejarlos así es deuda que se paga sola con el tiempo:

| Qué | Dónde | Estado en la web |
|---|---|---|
| **Import de grabaciones** | `routers/imports.py` — `POST /api/meetings/{id}/import` | No hay un solo `<input type="file">` ni un `FormData` en todo `apps/web/src` |
| **Comentarios** | `routers/comments.py` — 4 endpoints (crear, listar, resolver, borrar), con menciones `@Nombre` → notificaciones | Cero referencias en el frontend |
| **Grafo de memoria** | `routers/memory.py` | **Parcial**: `GET /api/dashboard` y `GET /api/prepare-meeting` sí se usan. Quedan sin UI `/api/memory/entities`, el detalle de entidad, y los tres de reuniones relacionadas (listar, confirmar, rechazar) |

Nota sobre el import: el pipeline de import funciona de punta a punta del lado
del servidor. Lo único que falta es el botón.

### ⚠️ Echo corre en UN SOLO proceso. No lo escales sin leer esto

Dos piezas viven en la memoria de un único proceso Python, sin nada compartido
detrás: el **bus de eventos en vivo** (`services/live_bus.py`, un dict de
`asyncio.Queue`) y el **rate limiting** (`deps.py`, un dict de deques).

Hoy funciona porque `docker-compose.prod.yml` arranca **un solo uvicorn sin
`--workers`**. Esa ausencia es lo que sostiene el diseño.

Si agregás `--workers 2`, un segundo contenedor de API o cualquier réplica:

- **La transcripción en vivo deja de verse.** El WebSocket del espectador cae
  en un worker y los segmentos entran por otro; el `publish` escribe en un
  dict que nadie está mirando.
- **El rate limit se divide por la cantidad de workers.** Cada proceso cuenta
  aparte: 5 intentos con 4 workers toleran 20.

**Y no vas a ver un solo error.** No hay excepción, ni log, ni healthcheck en
rojo: el bus encuentra cero suscriptores y retorna normal. Todo «anda», sólo
que la transcripción en vivo no aparece. Es el tipo de falla que se busca
durante días en el frontend.

Antes de escalar hay que mover el bus a un pub/sub real (Redis, NATS, LISTEN/
NOTIFY de Postgres) y el rate limit a un store compartido. Ver
[docs/architecture.md](docs/architecture.md).

### Otras trampas que conviene saber de antemano

- **Migraciones**: los índices HNSW de pgvector (`ix_segments_embedding`,
  `ix_memory_entities_embedding`) se crean por SQL crudo en la migración
  inicial y **no están declarados en los modelos**. `alembic check` ya reporta
  `Detected removed index` para los dos: es ruido esperado. El problema es que
  `alembic revision --autogenerate` **va a generar un `drop_index` de ambos**;
  si esa migración se aplica, la búsqueda semántica pasa a escaneo secuencial
  sin ningún error visible. Hay comentarios de advertencia junto a las dos
  columnas `embedding`. Si autogenerás, borrá el `drop_index` a mano.
- **Routers opcionales que desaparecen en silencio**: `main.py` importa los
  routers en un loop con `except ModuleNotFoundError: continue`. Hoy
  `insights` figura en la lista y **el archivo no existe**, así que no se monta
  y nadie se entera. Peor: ese `except` también se traga un
  `ModuleNotFoundError` lanzado *dentro* de un router (una dependencia que
  falta), y un router entero puede evaporarse de la API sin un solo log.
- **Echo Bridge desde producción**: los `allowed_origins` por defecto son sólo
  `localhost`. Desde el dominio deployado el bridge responde **403** y la web
  ofrece el modo cloud como si no hubiera bridge. Hay que agregar el dominio a
  mano en su `config.json` — ver [docs/bridge.md](docs/bridge.md).

## Pendientes que dependen del usuario

1. **Modelo real de acta** → Ajustes → Formato de acta (o `PUT
   /api/org/minutes-template`).
2. **API keys** de LLM/STT/embeddings → Ajustes → IA.
3. **Murmur**: indicar dónde está instalado (o el comando exacto) en la config
   de Echo Bridge para que sea el motor local preferido. Si vas a usarlo desde
   el dominio de producción, agregá ese origin a `allowed_origins`.
4. **Motivos de reunión** (institucional) → Ajustes → Motivos. La lista
   arranca vacía a propósito: la define cada institución.
5. **`SUPERADMIN_EMAILS`** en el `.env` + reinicio de la API, si querés el
   panel de organizaciones. No se otorga desde la UI.
6. **Google** (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` + `API_PUBLIC_URL`),
   si querés login con Google o subida de actas a Drive.
