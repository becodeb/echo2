# Arquitectura de Echo

## Componentes

| Componente | Stack | Corre en |
|---|---|---|
| Echo API | FastAPI, SQLAlchemy async, Alembic | Docker (python 3.12) |
| Base de datos | PostgreSQL 17 + pgvector | Docker |
| Echo Web | React 18, Vite, TS, Tailwind 4, TanStack Query | pnpm dev / estático |
| Echo Bridge | Rust (axum, tokio) | Nativo, 127.0.0.1:8974 |
| Echo Device | ESP32-S3, Arduino/PlatformIO | Hardware |

## Flujos de audio (privacy-first)

**Modo bridge (preferido):**
```
mic → AudioWorklet (PCM16 16k) → ws://127.0.0.1:8974/stt → motor local
    → texto {partial|final} → browser → wss API /meetings/{id}/ws → DB
```
El audio no sale de la máquina. El buffer del bridge vive en RAM; si el motor
es un CLI, el WAV temporal se borra al instante (NamedTempFile).

**Modo cloud (fallback):**
```
mic → PCM16 → wss API → buffer RAM (ventana 6 s) → provider STT → texto → DB
                                   └── chunk descartado tras transcribir
```

**Import de grabación:** upload → ffmpeg → provider STT → texto → **archivo
eliminado** (finally garantizado).

**Echo Device:** ESP32 → wss `/api/devices/stream` (token de dispositivo) →
misma ingesta cloud; o apuntado al bridge de una PC en la sala (LAN).

## Pipeline de finalización

`POST /meetings/{id}/finish` encola `run_finalize_pipeline`:

1. `consolidate_speakers` — agrupa `speaker_hint` de los segmentos en filas
   `Speaker` (los hints vienen del motor local con speaker turns, del canal
   mic/sistema, o del dispositivo).
2. Extracción estructurada (LLM): temas, decisiones (+contexto), tareas
   (+responsable+fecha textual), preguntas, riesgos, menciones, timeline,
   próximos pasos. **Single-pass** hasta ~24k chars; **jerárquico** (por
   secciones con merge+dedupe) para reuniones largas.
3. Resolución de fechas relativas (`services/dates.py`, sin dependencias):
   "viernes" + fecha de la reunión → `2026-08-28`; se guardan ambas.
4. Embeddings de segmentos (batch, con zero-padding a dim 1536 — preserva
   coseno) → índice HNSW.
5. Resúmenes ejecutivo + detallado (jerárquico si es larga: sección → global).
6. **Acta**: template de la org (source of truth) + datos estructurados +
   transcript → `ActaGenerator` (regla dura: no inventar; faltantes = "No
   especificado durante la reunión") → `ActaVerifier` contrasta cada claim
   contra el transcript (contexto por timestamp + léxico, veredicto
   verified/weak/missing con evidencia en ms).
7. Memoria organizacional: entidades (project/person/topic) + relaciones
   (decided/assigned/mentioned) con evidencia → sugerencia de reuniones
   relacionadas.
8. Notificaciones «Tu acta está lista».

Cada etapa reporta progreso por `live_bus` (WS) y `processing_state`. Si el
LLM no está configurado, las etapas de IA quedan `skipped` y la UI lo dice.

## RAG y chat

- Retrieval híbrido: pgvector (coseno, HNSW) + full-text español (tsvector
  GIN), dedupe, **siempre filtrado por organization_id**.
- Chat de reunión: contexto = fragmentos con timestamps; system prompt
  prohíbe conocimiento externo; sin evidencia → "No encontré eso en esta
  reunión."
- Chat global: fragmentos multi-reunión + hechos del grafo de memoria; cita
  «Título», fecha y [MM:SS]; narra evoluciones cronológicamente.

## Tiempo real

`live_bus` (pub/sub in-process por reunión) difunde a los WS viewers:
segmentos finales, parciales efímeros (no persisten), contadores de insights
en vivo (cada ~8 segmentos, con lock anti-reentrada), estado del pipeline y
warnings. El frontend re-conecta con backoff; el transcript confirmado nunca
se pierde (vive en DB).

### ⚠️ Esto obliga a correr un solo proceso de API

Leé esto antes de escalar. Hay dos estructuras que viven **en la memoria de un
único proceso Python**, sin Redis ni nada compartido detrás:

| Qué | Dónde | Qué es realmente |
|---|---|---|
| Bus de eventos en vivo | `services/live_bus.py` | `dict[str, set[asyncio.Queue]]` |
| Rate limiting | `deps.py` (`_buckets`) | `dict[str, deque]` de timestamps |

Hoy funciona porque `docker-compose.prod.yml` arranca **un solo uvicorn sin
`--workers`**. Esa línea es la que sostiene todo el diseño.

Qué se rompe si agregás `--workers 2`, un segundo contenedor de API, o
cualquier réplica horizontal:

- **La transcripción en vivo deja de llegar.** El WS del viewer aterriza en el
  worker A y los segmentos entran por el worker B: el `publish` de B escribe en
  un dict que el viewer de A no está mirando. La pantalla queda vacía.
- **El rate limiting se divide por la cantidad de workers.** Cada proceso tiene
  su propio contador, así que un límite de 5 intentos con 4 workers tolera
  hasta 20.

**Lo peor es cómo falla: sin un solo error.** No hay excepción, no hay log, no
hay healthcheck en rojo. El `publish` encuentra cero suscriptores y retorna
normalmente; el rate limit simplemente cuenta menos. Todo "anda", sólo que la
transcripción en vivo no aparece y el límite no limita. Alguien va a perder
días buscando esto en el frontend.

Antes de escalar hay que mover el bus a un pub/sub real (Redis, NATS, LISTEN/
NOTIFY de Postgres) y el rate limit a un store compartido. Hasta entonces:
**un solo worker, y que quede escrito en el compose.**

## Decisiones técnicas destacadas

- **Puerto API 8787** (no 8000): en la máquina de desarrollo había otro
  servicio en 8000.
- **Embeddings con dimensión fija 1536 + zero-padding**: pgvector exige dim
  fija por columna; el padding con ceros preserva exactamente la similitud
  coseno entre vectores del mismo provider.
- **Diarización en el borde**: como el servidor jamás retiene audio, la
  separación de hablantes ocurre donde el audio vive (bridge/dispositivo) y
  viaja como `speaker_hint`; el servidor solo consolida.
  Que quede claro qué **no** hay: no existe ninguna interfaz
  `DiarizationProvider` ni ningún punto de extensión preparado para enchufar
  un modelo de embeddings de voz. Agregar identificación automática de
  hablantes (ECAPA/pyannote) es trabajo de diseño desde cero, no un plug-in.
  El campo `diarization_provider` que se puede setear en Ajustes → IA se
  persiste pero **nadie lo lee**: es config muerta.
- **Voice profiles: schema sin implementación**. `SpeakerProfile`
  (`models/meetings.py`) tiene columna de embedding y `consent_at`, y la
  migración crea la tabla, pero ningún código la lee ni la escribe. No hay
  endpoint para dar de alta un perfil ni nada que calcule ese embedding.
  Es una tabla vacía esperando una feature que no está escrita.
- **Actas versionadas**: cada edición crea `MinutesVersion` nueva; editar un
  acta aprobada la vuelve a "en revisión". El acta generada guarda su
  verificación.
- **Transcript editable con historial**: `SegmentRevision` conserva el
  original, invalida el embedding del segmento y audita quién editó.
