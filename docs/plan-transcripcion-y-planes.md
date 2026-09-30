# Plan: transcripción fiel, quién habló, planes y créditos

Escrito el 30/9/2026 para que otra sesión lo implemente de punta a punta. **Lo
que se haga acá va a producción cuando termine**: calidad de producción, tests,
commits chicos, y confirmar con Bauti (el dueño) antes de cada deploy.

---

## 0. Qué es Echo y qué leer primero

Echo (https://echo.becode.com.ar) graba reuniones de colegios (entrevistas con
familias, reuniones de equipo/internas), las transcribe en vivo, al finalizar
separa quién habló, y genera acta, resumen, tareas con responsables, memoria de
la sede y un chat con IA sobre la reunión. Multi-organización: cada colegio es
una organización ("sede"), con niveles, familias y grupos internos.

- Repo: `github.com/becodeb/echo2`, rama `main`. Monorepo:
  - `apps/api`: FastAPI + SQLAlchemy async + Postgres 17 (pgvector). Migraciones
    alembic en `apps/api/alembic/versions` (idempotentes, mirar 0013-0015).
  - `apps/web`: React + Vite + TypeScript.
  - `apps/bridge`: motor local en Rust (modo "bridge", el audio no sale de la PC).
  - `apps/video`: demo en Remotion (no se despliega).
- Deploy: Coolify (https://coolify.becode.com.ar), app "echo", uuid
  `qj2b8e1aqtxssf5ylcn13ntb`, compose `docker-compose.prod.yml`, rama main. El
  token de la API de Coolify y cómo llegar a la base están en
  `~/.claude/CLAUDE.md` de esta PC. **No redeployar sin confirmar.**
- Servidor de producción: 2 vCPU viejos, 4 GB RAM, carga alta, disco al 85%.
  **No correr modelos de voz en el servidor**: todo por API.

Leer antes de tocar nada:
1. `README.md` y `docs/architecture.md`, `docs/security.md`.
2. Camino del audio: `apps/api/echo_api/routers/live.py` (WebSocket en vivo,
   cortes con `services/stt/windowing.py`, filtros en `services/stt/channels.py`),
   `services/recording.py` (audio de trabajo `.pcm`), `services/diarization.py`
   (pasada final), `services/pipeline.py` (qué corre al finalizar),
   `services/stt/*` (proveedores), `services/ai_settings.py` (keys por sede).
3. Privacidad: `services/privacy.py` (seudonimiza nombres y datos antes de la IA).
4. Exportaciones: `routers/exports.py`, `apps/web/src/components/ExportMenu.tsx`.
5. El banco de pruebas: `apps/api/bench/` (ver sección 2).

Tests: `docker compose up -d db` y, en `apps/api`,
`DATABASE_URL=postgresql+asyncpg://echo:echo_dev_pw@localhost:5433/echo pytest`
(necesita `ffmpeg` en el PATH). La web: `npm run build` en `apps/web`.

---

## 1. Keys (dónde están; nunca commitearlas)

| Uso | Dónde | Variable |
|---|---|---|
| Producción, Groq | Envs de Coolify (app echo) | `GROQ_API_KEY` (ya cargada; `docker-compose.prod.yml` ya la pasa al api) |
| Producción, ElevenLabs | Envs de Coolify (app echo) | `ELEVENLABS_API_KEY` (ya cargada; **falta** pasarla en `docker-compose.prod.yml` y leerla en `echo_api/config.py`) |
| Producción, OpenAI | Envs de Coolify | `OPENAI_API_KEY` (hoy la usa el STT; queda para el LLM del acta/chat) |
| Pruebas locales | `apps/api/bench/.env` del worktree `D:\Descargas\echo-transcripcion` (en `.gitignore`) | `GROQ_API_KEY`, `ELEVENLABS_API_KEY`, `OPENAI_API_KEY` (de prueba) |

Bauti pidió **no gastar más tokens de OpenAI en pruebas**: probar con Groq/ElevenLabs.

---

## 2. Lo que se midió (banco `apps/api/bench/`)

`bench/stt_bench.py` corre un audio por varios modelos y reproduce producción
(el en vivo de `live.py` y la pasada final de `diarization.py`). `bench/metrics.py`
mide WER, frases de más, frases inventadas y persona correcta (por palabra, turno
y tiempo). Caso `bench/casos/2026-09-30` (reunión eb3ce903, 2:15, 5 personas,
`reference.txt` marcado por Bauti). Resultados en `results.json`,
`results.repeat.json` y `results.local.md`. Segundo audio de prueba: reunión del
27/9 (20 s, 3 personas: Bautista Goñi, Vanina, "el Choto").

Hallazgos que explican los bugs de producción:
- El turno "Hablante" gigante de las 02:10 era **la pista del en vivo devuelta
  por el modelo**: `live.py` manda los últimos 300 caracteres como `prompt` y en
  un tramo casi mudo gpt-4o-transcribe devolvió exactamente eso.
- **Esa pista también causa las repeticiones**: con pista, "uno dos tres
  probando" sale 12 veces; sin pista, 2 (se dijo 5).
- **No había eco acústico** en el audio (mono, sin copias demoradas).
- La pasada final de esa reunión **descartó su propio texto** y dejó el del en
  vivo con voces repartidas; los tramos sin voz cercana quedaron sin persona.
- **gpt-4o-transcribe con el audio entero entra en bucle** ("¿Cómo estás?" x100)
  en 6 de 12 corridas.
- gpt-4o-transcribe-diarize encuentra 2-4 personas de 5; nunca a D ni a E.

Comparación (audio del 30/9, referencia de Bauti):

| Opción | Texto | Personas |
|---|---|---|
| Whisper large-v3-turbo (Groq o local), `language=es`, sin pista previa | WER 55%, sin bucles ni idiomas inventados, estable | no separa |
| ElevenLabs Scribe v2 (`language_code=spa`, `diarize=true`) | el más completo y natural (WER 78% solo porque la referencia no tiene el tramo 0:26-1:47) | A y B perfectas; C, D, E pegadas a A (el celular se movía) |
| OpenAI (lo actual) | 72% a 1700% (bucles) | 32-46% del tiempo |
| Parakeet v3 / Phonon-2 | se pasa al inglés / solo inglés | — |

Audio del 27/9: Groq y ElevenLabs transcriben igual de bien; **ElevenLabs
separó a las 3 personas sin un error** (Bautista, Vanina dos veces, el Choto).

---

## 3. Decisiones tomadas

1. **En vivo: Groq `whisper-large-v3-turbo`** (US$ 0,04/h), `language` fijo de la
   sede (es), `temperature=0`, **sin pista de contexto** (solo el vocabulario de
   la sede, si hay), cortes de `windowing.py`, filtros de `channels.py`, y
   descartar un tramo cuyo texto repite la pista o el tramo anterior.
2. **Pasada final**:
   - Con personas (plan pago o crédito usado): **ElevenLabs Scribe v2**
     (US$ 0,22/h), `language_code=spa`, `diarize=true`, `timestamps_granularity=word`,
     `tag_audio_events=false`, vocabulario de la sede como keyterms (+US$ 0,05/h)
     y **detección de entidades** (+US$ 0,07/h, ver 4).
   - Sin personas: **Groq** sobre el audio entero (mejor contexto que el en vivo).
3. **Un solo camino en la pasada final**: el texto y las personas salen del mismo
   resultado (Scribe trae palabra, tiempo y persona). Se borra la "red de
   seguridad" que agregaba frases de la separación (`merge_text_with_voices`) y
   el mezclado de dos fuentes. **Ningún turno sin persona** cuando hubo
   separación: una palabra sin persona hereda la del vecino más cercano.
4. **Respaldo**: si ElevenLabs falla o no tiene cuota, se usa Groq para el texto,
   la reunión queda marcada "personas pendientes" y se reintenta la separación
   más tarde (no se etiqueta mal).
5. **OpenAI deja de usarse para transcribir.** Queda solo como LLM (acta,
   resumen, chat), salvo que se decida otra cosa.
6. **Northfield School no paga**: sus miembros tienen todo habilitado (Bauti los
   costea; son los usuarios de prueba). Identificarla en la base por su dominio
   en `organizations.join_rules` / `AUTO_JOIN_DOMAINS` (empieza con "nort...");
   confirmar el id con una consulta antes de marcarla.
7. Cuenta de ElevenLabs: **plan Starter** (US$ 6/mes; 27 h de Scribe v2 incluidas
   para TODO Echo, no por colegio; después US$ 0,22/h). Groq: nivel gratis hasta
   que haga falta (20 pedidos/min, 2.000/día, 8 h de audio/día: aprieta con más
   de 2 reuniones en simultáneo).

---

## 4. ⚠️ Menores de edad (bloqueante legal)

**La política de privacidad de ElevenLabs (actualizada 20/5/2026, sección 11)
prohíbe mandarle voces de menores de 18 años**: dice que los usuarios tienen
prohibido subir, transmitir o poner a su disposición datos de voz de menores de
18, o usarlos en cualquiera de sus servicios (https://elevenlabs.io/privacy-policy,
"Children's Privacy"). Sus Términos exigen además que el usuario sea mayor de 18.

Además, en planes que no son Enterprise ElevenLabs **usa los datos para
entrenar salvo que se desactive** (Perfil → Terms and privacy → Data use), no
publica cuánto guarda el audio de STT, y la retención cero (`enable_logging=false`)
es **solo Enterprise**. Guarda datos de voz hasta 3 años.

Comparación de proveedores sobre esto:
- **Groq**: por defecto no guarda nada; logs de hasta 30 días solo para
  errores/abuso; **retención cero disponible para todos** (Settings → Data
  Controls). No menciona menores. → apto para reuniones con alumnos.
- **OpenAI** (lo que se usa hoy): exige retención cero para datos de menores de
  13 años. Hoy Echo no la tiene → otro motivo para dejarlo para STT.
- **AssemblyAI**: sin cláusula de menores en sus términos; transcripts 30 días
  por defecto, TTL de 1 día y opt-out de entrenamiento en plan pago.
- **Mistral**: sus términos de consumidor piden consentimiento para menores de 13.

Consecuencia para el diseño: **toda reunión donde hablen menores NO va a
ElevenLabs** (ni al agente de voz). Ver pregunta P1.

---

## 5. Planes y créditos (propuesta, falta cerrar con Bauti: sección 8)

- **Base (gratis, para colegios y docentes)**: en vivo y pasada final con Groq,
  sin separar personas (salvo llamadas de Meet/Zoom, que se separan por canal).
  Reuniones ilimitadas (con un tope anti-abuso). Incluye **4 reuniones por mes
  con personas** (créditos), que la persona activa al crear la reunión cuando la
  necesita. Crédito simple: **1 reunión = 1 crédito** (hasta 1 h; más larga, 2).
- **Premium (organización)**: pasada final siempre con ElevenLabs (si no hay
  menores). Precio a definir.
- **Individual US$ 5/mes**: 5 h de reuniones al mes con todo (Groq en vivo +
  ElevenLabs al finalizar). Costo nuestro: ~US$ 1,30 + LLM + comisión de cobro.
- **Individual US$ 10/mes**: lo anterior + **hablar por voz con el asistente de
  Echo** (ElevenLabs Agents: US$ 0,08/min + el LLM aparte; el Starter trae 75
  min/mes para toda la cuenta). Con tope de minutos (p. ej. 30 min/mes ≈ US$ 2,40).
  **Solo individuales, nunca organizaciones.** Solo mayores de 18.
- Medir consumo real por sede y por persona (horas de Groq y ElevenLabs, minutos
  de voz) desde el día 1: tabla de uso mensual.

---

## 6. Tareas (en orden; cada una con tests y commit propio)

1. **Configuración**: `ELEVENLABS_API_KEY` en `config.py` y en
   `docker-compose.prod.yml`. Proveedores nuevos en `services/stt/`:
   `groq` ya existe en `get_stt_provider` (revisar parámetros: `temperature=0`,
   sin pista de contexto) y `elevenlabs.py` nuevo (Scribe v2 batch).
2. **En vivo con Groq sin pista** (`routers/live.py`): sacar `context=recent_text`,
   filtrar un texto igual a la pista o al tramo anterior, idioma de la sede.
   Test que reproduce el turno de las 02:10 (el modelo devuelve la pista).
3. **Pasada final nueva** (`services/diarization.py`, reescritura): una fuente
   (Scribe o Groq), turnos por persona a partir de las palabras, sin red de
   seguridad, sin turnos huérfanos, respaldo y reintento. Tests con respuestas
   grabadas (fixtures) de las reuniones del 30/9 y del 27/9: sin duplicados, sin
   "Hablante", 3 personas en la del 27/9.
4. **Entidades → privacidad**: pedir detección de entidades a Scribe y sumar los
   nombres/datos detectados a la lista de `services/privacy.py` de esa reunión
   antes de mandar nada al LLM. Test: un nombre que no está en ninguna nómina no
   le llega a la IA.
5. **Alucinaciones**: ampliar `channels.py` (Amén, "- " sueltos, subtítulos,
   texto en otro alfabeto/idioma) y usar `no_speech_prob`/`avg_logprob` de Groq.
6. **Planes, créditos y uso** (migración idempotente): plan por organización y
   por usuario individual, créditos mensuales, tabla de uso (segundos de audio
   por proveedor, minutos de voz), exención de Northfield, límites.
7. **Crear reunión** (`apps/web/src/components/NewMeetingModal.tsx`): mostrar
   claramente qué va a hacer la IA en esta reunión según plan y créditos:
   transcripción, quién habló (sí/no, gasta 1 crédito), acta, tareas con
   responsables, chat con la IA, voz. Checkbox "¿hablan alumnos/menores?" (P1).
8. **Zoom/Meet/grabación de pantalla**: probar con una llamada real que el
   estéreo (micrófono/sistema) + Scribe separan bien; que la mezcla a mono de
   `recording.py` no pierda a quien habla bajo.
9. **Cobros** (P3) y **agente de voz** para el plan de US$ 10 (P4), al final.
10. **Banco**: agregar Groq y ElevenLabs como variantes de `stt_bench.py` y el
    caso 27/9; correrlo antes y después de cada cambio de la pasada final.

Criterio de terminado: las dos reuniones de prueba procesadas de punta a punta en
local con las keys de prueba dan transcript sin duplicados ni "Hablante", con
las personas separadas (27/9: 3 de 3), tests verdes, `npm run build` ok, y
Bauti confirma antes del deploy.

---

## 7. Cosas que Bauti tiene que hacer en las cuentas (no las hace la IA)

- ElevenLabs: desactivar el uso para entrenamiento (Perfil → Terms and privacy →
  Data use) y borrar del historial de Speech to Text las pruebas con el audio
  del 30/9 (tenía la voz de una alumna).
- Groq: activar Zero Data Retention (Settings → Data Controls). Para cargar
  saldo, pasar al plan pago desde Settings → Billing cuando haga falta.

---

## 8. Preguntas abiertas (contestarlas antes de las tareas 6-9)

- **P1. Menores**: ¿en qué reuniones hablan alumnos? Propuesta: checkbox al crear
  ("hablan alumnos/menores de 18"), marcado por defecto en reuniones con
  familias; si está marcado, pasada final con Groq (sin personas) o con
  AssemblyAI (separa personas, sin cláusula de menores, TTL 1 día).
- **P2. Créditos**: ¿son por docente o por colegio? ¿4 por mes?
- **P3. Cobro**: ¿MercadoPago (pesos) o Stripe/Lemon Squeezy (dólares)?
  ¿Existen hoy usuarios individuales sin colegio, o hay que crear ese tipo de cuenta?
- **P4. Agente de voz**: ¿qué LLM ("V4 Flash": DeepSeek V4 Flash, Gemini Flash,
  GPT mini)? ¿Cuántos minutos por mes en el plan de US$ 10?
- **P5. Premium para colegios**: ¿precio? ¿qué incluye además de las personas?
- **P6. "Groq infinito"**: ¿tope anti-abuso (horas/mes por docente)?
