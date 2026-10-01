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
| Pruebas locales | `apps/api/bench/.env` (en `.gitignore`; copiado a cada worktree) | `ELEVENLABS_API_KEY` = la key **de prueba** (plan gratis; usarla para probar, no la de producción), `GROQ_API_KEY`, `OPENAI_API_KEY` (de prueba) |

Bauti pidió **no gastar más tokens de OpenAI en pruebas**: probar con Groq/ElevenLabs.

**Si trabajás en otra PC** (no en la que se armó el banco): `apps/api/bench/.env`,
`apps/api/bench/.cache` y los audios de prueba no están en git (tienen keys y
voces). Pedile a Bauti que te copie `bench/.env` (o que te
pase las keys de prueba de Groq y ElevenLabs) y los dos mp3 de la sección 2. Sin
`.cache`, el banco vuelve a pedir a las APIs: **no correr las variantes de
OpenAI** (`--only` con las de Groq/ElevenLabs).

---

## 2. Lo que se midió (banco `apps/api/bench/`)

`bench/stt_bench.py` corre un audio por varios modelos y reproduce producción
(el en vivo de `live.py` y la pasada final de `diarization.py`). `bench/metrics.py`
mide WER, frases de más, frases inventadas y persona correcta (por palabra, turno
y tiempo). Caso `bench/casos/2026-09-30` (reunión eb3ce903, 2:15, 5 personas,
`reference.txt` marcado por Bauti). Resultados en `results.json`,
`results.repeat.json` y `results.local.md`. Segundo audio de prueba: reunión del
27/9 (20 s, 3 personas: Bautista Goñi, Vanina, "el Choto").

Audios (no van al repo): `D:\Descargas\2026-09-30 Reunión 3092026.mp3` y
`D:\Descargas\2026-09-27 Reunión 2792026.mp3`. Para correr el banco: un venv con
`numpy httpx imageio-ffmpeg` más `apps/api/requirements.txt`, y
`python bench/stt_bench.py --case bench/casos/2026-09-30 --audio "<mp3>"`
(las respuestas quedan en `bench/.cache`; no volver a pedirle a OpenAI).

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
- **Groq**: **no entrena con los datos, por contrato** (Services Agreement,
  sección 4.2, vigente desde 22/6/2026: no puede usar inputs ni outputs para
  entrenar sin permiso explícito del cliente); por defecto no guarda nada; logs
  de hasta 30 días solo para errores/abuso; **retención cero disponible para
  todos** (console.groq.com → Settings → Data Controls). No menciona menores. →
  apto para reuniones con alumnos.
- **OpenAI** (lo que se usa hoy): exige retención cero para datos de menores de
  13 años. Hoy Echo no la tiene → otro motivo para dejarlo para STT.
- **AssemblyAI**: sin cláusula de menores en sus términos; transcripts 30 días
  por defecto, TTL de 1 día y opt-out de entrenamiento en plan pago.
- **Mistral**: sus términos de consumidor piden consentimiento para menores de 13.

Consecuencia para el diseño: **toda reunión donde hablen menores NO va a
ElevenLabs** (ni al agente de voz). Ver pregunta P1.

---

## 5. Planes y créditos (cerrado con Bauti el 30/9)

- **Base (gratis, docentes y cualquiera)**: en vivo y pasada final con Groq, sin
  separar personas (salvo llamadas de Meet/Zoom, que se separan por canal).
  Reuniones sin límite de producto. **4 créditos por mes POR DOCENTE**: cada
  crédito es una reunión "con personas" (ElevenLabs al finalizar), que la
  persona activa al crear la reunión solo cuando la necesita. 1 reunión = 1
  crédito (una de más de 1 h, 2). Se renuevan cada mes, no se acumulan.
- **Colegios / instituciones (premium)**: ~US$ 65/mes por institución; pasada
  final siempre con ElevenLabs (salvo reuniones con menores). En la UI **no se
  muestra el precio ni el mail**: botón **"Contact sales"**.
- **Individual US$ 5/mes**: 5 h de reuniones al mes con todo (Groq en vivo +
  ElevenLabs al finalizar). Costo nuestro: ~US$ 1,30 + LLM + comisión de cobro.
- **Individual US$ 10/mes**: lo anterior + **conversación por voz con el
  asistente de Echo** (speech-to-speech). ElevenLabs Agents (US$ 0,08/min + LLM
  aparte) con la voz del modelo **Eleven v4** de ElevenLabs (el nuevo; confirmar
  en la doc de Agents que se puede usar ahí y su latencia; si no, Flash). Voz:
  elegir de su biblioteca una voz linda, cálida y "piola" en castellano
  rioplatense (probar 3 y dejar la mejor). LLM del agente: **el más barato de los
  que ofrece ElevenLabs Agents que ande bien en castellano** (probar 2-3 de las
  líneas Flash-Lite / nano / mini con conversaciones reales). **30 minutos de voz
  por mes.** Solo cuentas individuales, nunca organizaciones, solo mayores de 18.
- **Rentabilidad (peor caso, usando todo el mes; estimada)**:
  | | Individual US$ 5 | Individual + voz US$ 10 |
  |---|---|---|
  | Reuniones 5 h (Groq US$ 0,20 + Scribe US$ 1,10) | 1,30 | 1,30 |
  | LLM de actas/chat (estimado) | 0,20 | 0,20 |
  | Voz 30 min (US$ 0,08/min + LLM) | — | 2,50 |
  | Comisión de cobro (~8%, a confirmar con MercadoPago) | 0,40 | 0,80 |
  | **Ganancia** | **~US$ 3,10 (62%)** | **~US$ 5,20 (52%)** |
  En la práctica casi nadie usa todo, así que el margen real es mayor. Las
  horas y minutos que trae el Starter de ElevenLabs (27 h de Scribe, 75 min de
  agente, para toda la cuenta) bajan el costo al principio.
- **Cuentas individuales**: hay que crearlas. Al registrarse, si el dominio del
  mail coincide con una organización (`join_rules`, `services/org_join.py`), la
  persona entra sola a esa organización (como hoy). Si no, se crea su cuenta
  individual (una organización personal de una persona) con el plan Base. Una
  persona dentro de un colegio también puede pagar un plan individual para ella.
- **Northfield School**: todo habilitado, sin pagar.
- **Topes contra abuso**: sin valor fijo en el código; los define un superadmin
  (`SUPERADMIN_EMAILS`: becodestudio@gmail.com y gonibauti@gmail.com) por plan,
  por organización o por usuario, desde el panel de admin.
- **Cobro**: todavía no hay (probablemente MercadoPago más adelante). **No crear
  links de pago.** Los botones "Suscribirme" / "Contact sales" registran el
  pedido (quién, qué plan, cuándo) y **avisan a Becode** (notificación a los
  superadmins y mail a becodestudio@gmail.com desde el servidor), sin mostrar el
  mail en la UI. A la persona se le confirma "te contactamos".
- **Uso y costo desde el día 1** (ver tarea 11): segundos de audio por
  proveedor/modelo, minutos de voz, tokens de LLM, en dólares.

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
   transcripción, quién habló (sí/no, gasta 1 crédito, cuántos quedan), acta,
   tareas con responsables, chat con la IA, voz. Toggle **"Hablan alumnos
   (menores de 18)"**, **desactivado por defecto** (el 90% de las reuniones son
   sin menores); activado, la reunión no va a ElevenLabs y se explica por qué.
8. **Zoom/Meet/grabación de pantalla**: probar con una llamada real que el
   estéreo (micrófono/sistema) + Scribe separan bien; que la mezcla a mono de
   `recording.py` no pierda a quien habla bajo.
9. **Cobros** (P3) y **agente de voz** para el plan de US$ 10 (P4), al final.
10. **Banco**: agregar Groq y ElevenLabs como variantes de `stt_bench.py` y el
    caso 27/9; correrlo antes y después de cada cambio de la pasada final.
11. **Panel de consumo**: por usuario (cuánto gastó de cada modelo: Groq,
    Scribe, Agents, LLM, en horas/minutos y US$), por organización (sus admins
    ven a cada miembro) y global para los superadmins de Becode (todas las
    organizaciones y los individuales, incluidos los que están en una
    organización pero pagan un plan individual). Filtros por mes.
12. **Página de planes/billing**: tarjetas Gratis, Individual US$ 5, Individual +
    voz US$ 10 e Instituciones ("Contact sales"), con los créditos que quedan.
    Botones según la sección 5 (sin links de pago; avisan a Becode).
13. **Muestra de voz**: pedirla en el registro (después de crear la cuenta) y,
    para quien no la tiene, un anuncio **una sola vez** al volver a entrar
    (guardar que ya lo vio). Reusar "Mi voz" (`routers/my_voice.py`, migración
    0015) y usarlas como voces conocidas en la pasada final.
14. **Legal en la landing**: términos y privacidad claros: qué proveedores
    procesan el audio (Groq, ElevenLabs, el LLM), que no se usa para entrenar
    (ElevenLabs: desactivado en la cuenta el 30/9; Groq: por contrato; el LLM del
    acta: **verificar su política antes de afirmarlo**; lo que no se pueda
    garantizar no se escribe), qué se guarda y cuánto, reuniones con
    menores, consentimiento/aviso de grabación a las familias. Recomendar que
    lo revise un abogado.

### Estética (tareas 7, 11, 12, 13)

Bauti quiere la estética de ElevenLabs (elevenlabs.io/app): todo redondeado,
tarjetas con bordes suaves, mucho aire, transiciones y animaciones cuidadas en
cada click, cambios de estado fluidos (skeletons, fades, contadores que se
animan). Mirar cómo muestran planes, créditos y consumo en su app y su página de
precios, e inspirarse fuerte en eso, adaptado a los colores de Echo.

Criterio de terminado: las dos reuniones de prueba procesadas de punta a punta en
local con las keys de prueba dan transcript sin duplicados ni "Hablante", con
las personas separadas (27/9: 3 de 3), tests verdes, `npm run build` ok, y
Bauti confirma antes del deploy.

---

## 7. Cosas que Bauti tiene que hacer en las cuentas (no las hace la IA)

- ElevenLabs: uso para entrenamiento **ya desactivado** (30/9). Bauti confirmó
  que ninguno de los audios de prueba tiene voces de menores: no hay nada que
  borrar por eso.
- Groq: activar Zero Data Retention (console.groq.com → Settings → Data
  Controls; lo puede hacer un admin de la organización de Groq). Entrenamiento no
  hay que desactivarlo: por contrato no entrenan. Para cargar saldo, pasar al
  plan pago desde Settings → Billing cuando haga falta.

---

## 8. Decisiones de Bauti (30/9) y lo que falta

Respondidas:
- Menores: toggle al crear, **desactivado por defecto**; activado → sin ElevenLabs
  (pasada final con Groq, sin personas).
- Créditos: **4 por mes por docente**.
- Colegios: ~US$ 65/mes por institución, en la UI solo "Contact sales".
- Cobro: todavía nada; botones que avisan a Becode, sin links de pago.
- Voz: modelo **Eleven v4** de ElevenLabs para la conversación por voz.
- Topes: los pone un superadmin desde el panel, sin número fijo en el código.
- ElevenLabs: Bauti ya desactivó "Improve the models for everyone" (entrenamiento).

- Cuentas individuales: se crean; si el dominio coincide con una organización,
  entra sola; si no, cuenta individual con plan Base.
- Voz: 30 min/mes en el plan de US$ 10; el LLM más barato que ande bien; voz
  linda en rioplatense.
- Groq: no entrena por contrato; Bauti activa la retención cero en su cuenta. Si
  algo de privacidad no se puede garantizar, no se promete en la web: Bauti lo
  explica en persona en la venta.

Si surge una duda que no está acá, preguntarle a Bauti antes de decidir.

---

## 9. Estado al 30/9 (fin de la sesión de implementación)

Todo en la rama `planes-y-transcripcion`, commits chicos, tests verdes (API
~200 tests, web 11) y `npm run build` ok. **No está deployado.**

| Tarea | Estado |
|---|---|
| 1. Configuración y proveedores | Hecha: `ELEVENLABS_API_KEY` (config y compose), `services/stt/elevenlabs.py`, Groq con temperature 0. |
| 2. En vivo con Groq sin pista | Hecha: sin `context`, descarta un tramo que repite el anterior, idioma fijo. Groq antes que OpenAI sin config de la sede. |
| 3. Pasada final nueva | Hecha: Scribe (con personas) o Groq (sin), turnos desde las palabras, sin red de seguridad, respaldo con reintento cada 15 min. Fixtures reales de 30/9 y 27/9 en `apps/api/tests/fixtures`. |
| 4. Entidades → privacidad | Hecha: `meta.detected_entities` entra a la seudonimización. |
| 5. Alucinaciones | Hecha: bucles, frases sueltas, `avg_logprob` (Groq devuelve siempre `no_speech_prob = 0`). |
| 6. Planes, créditos y uso | Hecha: migraciones 0016-0017, `services/plans.py`, panel de superadmin. |
| 7. Crear reunión | Hecha: "Lo que va a hacer Echo" + toggle de menores. |
| 8. Zoom/Meet | Parcial: la mezcla a mono suma los canales (antes promediaba y bajaba a la mitad a quien habla solo). **Falta probar con una llamada real.** |
| 9. Cobros y voz | Cobros: nada (decisión). Voz: hecha (`services/voice_agent.py`, `routers/voice.py`, "Hablar con Echo"). |
| 10. Banco | Hecho: variantes Groq/Scribe, caso 27/9, `results.groq-elevenlabs.md`. |
| 11. Panel de consumo | Hecho: `/usage` (persona y organización) y pestaña Consumo del panel de Becode. Tokens del LLM incluidos. |
| 12. Página de planes | Hecha: `/plans`, pedidos que avisan a Becode. |
| 13. Muestra de voz | Hecha: invitación una sola vez; las voces van delante del audio en la pasada final. |
| 14. Legal | Hecha: `/legal/privacidad` y `/legal/terminos`, landing corregida. |

De punta a punta en local con las keys de prueba: 27/9 → 3 de 3 personas, 0
turnos sin persona, 0 duplicados, 1 crédito; 30/9 → sin el turno "Hablante",
sin turnos sin persona, 3 personas de 5 (C, D, E pegadas, como en el banco).

Decisiones que tomó la implementación (confirmar con Bauti):
- Créditos: uno por hora empezada (70 min = 2, 3 h = 3). Si queda 1 crédito
  y la reunión duró 2 h, gasta el que queda y separa igual.
- Los créditos se reservan al decidir la pasada (de a una reunión por persona,
  así el último crédito no se gasta dos veces) y vuelven si la separación no
  sale (falla del todo, Scribe no devuelve nada o alguien corrigió el texto).
- Las muestras de "Mi voz" delante del audio están **apagadas** en la pasada
  final (`KNOWN_VOICES_IN_FINAL_PASS`): en la reunión del 27/9 partían a
  Bautista en dos personas. Prenderlas solo después de probar con más reuniones.
- Importar un audio y los Echo Devices pasan por la misma pasada final que el
  vivo (créditos, personas y consumo incluidos).
- Topes contra abuso (`meetings_per_day`, `audio_hours_per_month`): se
  aplican si están cargados en el plan, la organización o la persona.
- Cuenta individual: solo si el email no es de ningún colegio configurado y
  no tiene una invitación pendiente.
- LLM del agente de voz: `gemini-3.5-flash-lite` (probados también
  `gemini-3.1-flash-lite` y `gpt-5.4-nano`). Voz por defecto: Malena.
- LLM por defecto en Groq: `openai/gpt-oss-120b` (Groq retiró
  `llama-3.3-70b-versatile`).

Lo que tiene que hacer Bauti antes o después del deploy:
- Confirmar el deploy (migraciones 0016-0018 corren solas al arrancar).
- Panel de Becode → Organizaciones: poner a **Northfield en "Cortesía"** (no
  se pudo leer la base de producción desde esta sesión).
- Elegir la voz del agente escuchando `Downloads/echo-audios/voces-agente`
  (Malena, Agustín, Melisa, Tomás); si no es Malena, cargar su id en
  `ELEVENLABS_AGENT_VOICE_ID` en Coolify. Después: Panel → Planes y topes →
  "Crear o actualizar el agente".
- Coolify: `SMTP_HOST/PORT/USER/PASSWORD/FROM` para que los pedidos de plan
  lleguen por mail a becodestudio@gmail.com (sin eso quedan en el panel).
- Groq: pasar al plan pago antes de que haya más de una reunión a la vez (el
  gratis deja 20 pedidos por minuto y una reunión en vivo ya lo roza; ahora
  se espera y reintenta, pero el texto en vivo se atrasa).
- Decidir qué hacer con OpenAI y las reuniones con menores: el acta recibe
  texto seudonimizado, pero OpenAI pide retención cero para datos de menores
  de 13 (§4).
- Confirmar la referencia del 27/9 (`bench/casos/2026-09-27/reference.draft.txt`).
- Probar una llamada real de Meet o Zoom (tarea 8).
- Que un abogado revise `/legal/privacidad` y `/legal/terminos`.
