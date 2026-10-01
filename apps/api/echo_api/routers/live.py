"""WebSocket de reunión en vivo.

Roles de conexión:
  - recorder: la pestaña (o el bridge vía browser) que produce transcript.
      * Modo bridge: envía eventos JSON {type:"segment"|"partial"} con TEXTO
        (el audio nunca salió de la máquina del usuario).
      * Modo cloud: envía frames BINARIOS con PCM16 mono. El servidor los
        acumula en un buffer en RAM, los transcribe con el provider cloud
        configurado y descarta el audio inmediatamente.
  - viewer: recibe transcript/insights en tiempo real.

Audio de trabajo (services/recording.py): el audio que llega se agrega a un
archivo temporal de la reunión. Al finalizar se usa para separar quién habló
escuchando la reunión entera (services/diarization.py) y, si la reunión se
graba, para subirla al Drive de quien grabó; después se borra. Con el bridge
(que transcribe en la máquina) el navegador manda audio solo si se graba, con
`transcribe: false` en el hello: no se transcribe dos veces.

Una sola grabadora por reunión: si se conecta otra (otra pestaña, otro
dispositivo, un "Iniciar" tocado dos veces), la anterior se cierra con 4409.
Dos grabadoras mandando a la vez mezclaban el audio en pedacitos de 100 ms:
sonaba cortado y lento, y el modelo transcribía idiomas inventados.

Los tramos en vivo se cortan en las pausas (services/stt/windowing.py) y sus
tiempos se miden sobre ese archivo, así coinciden con los de la separación de
hablantes aunque el WebSocket se haya reconectado en el medio.

Autenticación: access token JWT por query param (el WS del browser no puede
mandar headers). El token es de corta duración y viaja por wss en producción.
"""
import asyncio
import contextlib
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from ..db import SessionLocal
from ..deps import user_can_access_meeting
from ..models import Meeting, Organization, OrganizationMember, TranscriptSegment, User
from ..security import decode_token
from ..services.ai_settings import get_vocabulary, resolve_stt
from ..services.background import spawn
from ..services.insights_live import maybe_extract_live_insights
from ..services.live_bus import live_bus
from ..services import plans
from ..services.plans import record_usage, stt_cost
from ..services.recording import PcmWriter, is_enabled, pcm_path, update_state
from ..services.stt import get_stt_provider
from ..services.stt.windowing import find_cut
from ..services.stt.channels import (
    attribute_speaker,
    downmix,
    is_noise_transcript,
    is_prompt_echo,
    is_silent,
    is_unreliable,
    repeats_previous,
    split_channels,
    strip_hallucinations,
)

log = logging.getLogger("echo.live")

# Grabadora activa de cada reunión (id de reunión → WebSocket).
_recorders: dict[str, WebSocket] = {}
# Audio que llega más rápido que esto respecto del tiempo real = hay más de
# una fuente mandando por la misma conexión.
MAX_REALTIME_RATIO = 1.5

router = APIRouter(tags=["live"])

MAX_SEGMENT_CHARS = 2000
# Espera antes de cada reintento de un tramo que Groq no transcribió.
LIVE_RETRY_WAITS = (1.0, 4.0)


async def _authorize(websocket: WebSocket, meeting_id: uuid.UUID) -> tuple[Meeting, User] | None:
    token = websocket.query_params.get("token", "")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4401, reason="Token inválido")
        return None
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(payload["sub"]))
        if not user or not user.is_active:
            await websocket.close(code=4401, reason="Usuario inválido")
            return None
        meeting = (
            await db.execute(
                select(Meeting).where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if not meeting:
            await websocket.close(code=4404, reason="Reunión no encontrada")
            return None
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == meeting.organization_id,
                    OrganizationMember.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if not member and user.is_superadmin:
            # Igual que el REST (deps.get_org_context): un superadmin entra a
            # cualquier sede como owner sin ser miembro. Sin esto, desde la
            # sede que visitaba no podía grabar: "No se pudo conectar".
            member = OrganizationMember(
                organization_id=meeting.organization_id, user_id=user.id, role="owner"
            )
        if not member:
            await websocket.close(code=4403, reason="Sin acceso")
            return None
        # Pertenecer a la organización no alcanza: una reunión privada sólo la
        # ve su creador, un compartido explícito o un admin. Esta regla es la
        # misma que aplica el REST y se consulta desde `deps` a propósito,
        # porque cuando estaba copiada acá se quedó vieja y este WS entregaba
        # el transcript en vivo de reuniones que el mismo usuario no podía
        # abrir por HTTP.
        if not await user_can_access_meeting(db, meeting, user, member.role):
            await websocket.close(code=4403, reason="Sin acceso")
            return None
        return meeting, user


async def _next_seq(db, meeting_id: uuid.UUID) -> int:
    current = (
        await db.execute(
            select(func.max(TranscriptSegment.seq)).where(TranscriptSegment.meeting_id == meeting_id)
        )
    ).scalar()
    return (current or 0) + 1


async def _store_segment(
    meeting: Meeting,
    text: str,
    start_ms: int,
    end_ms: int,
    confidence: float | None,
    speaker_hint: str | None,
) -> dict:
    """Persiste un segmento final y devuelve el evento para broadcast."""
    async with SessionLocal() as db:
        seq = await _next_seq(db, meeting.id)
        segment = TranscriptSegment(
            meeting_id=meeting.id,
            organization_id=meeting.organization_id,
            seq=seq,
            start_ms=max(0, int(start_ms)),
            end_ms=max(0, int(end_ms)),
            text=text[:MAX_SEGMENT_CHARS],
            confidence=confidence,
            is_final=True,
            speaker_hint=(speaker_hint or None),
        )
        db.add(segment)
        await db.commit()
        await db.refresh(segment)
        return {
            "type": "segment",
            "id": str(segment.id),
            "seq": segment.seq,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "text": segment.text,
            "confidence": segment.confidence,
            "speaker_hint": speaker_hint,
        }


async def _record_live_usage(meeting: Meeting, user_id: uuid.UUID | None, provider, seconds: float) -> None:
    """Segundos de audio que se mandaron a transcribir en vivo (panel de consumo)."""
    name = getattr(provider, "name", "desconocido")
    model = getattr(provider, "model", None)
    try:
        async with SessionLocal() as db:
            await record_usage(
                db,
                kind="stt_live",
                provider=name,
                model=model,
                unit="audio_seconds",
                quantity=round(seconds, 2),
                cost_usd=stt_cost(name, model, seconds),
                organization_id=meeting.organization_id,
                user_id=user_id,
                meeting_id=meeting.id,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - anotar el consumo no corta la reunión
        log.warning("live %s: no se pudo anotar el consumo: %s", meeting.id, exc)


@router.websocket("/api/meetings/{meeting_id}/ws")
async def meeting_ws(websocket: WebSocket, meeting_id: uuid.UUID):
    auth = await _authorize(websocket, meeting_id)
    if not auth:
        return
    meeting, user = auth
    await websocket.accept()

    channel = str(meeting.id)
    queue = await live_bus.subscribe(channel)
    role = "viewer"

    # Estado de ingesta cloud (solo si el recorder manda audio binario)
    audio_buffer = bytearray()
    sample_rate = 16000
    # 2 = PCM intercalado L(micrófono)/R(sistema); habilita atribución de
    # hablante por energía de canal.
    channels = 1
    stream_offset_ms = 0
    stt_provider = None
    vocabulary: list[str] = []
    stt_error_sent = False
    segments_since_insights = 0
    # El último tramo guardado: un tramo que lo repite entero es el modelo
    # devolviendo lo anterior, no alguien que habló.
    previous_text = ""
    # Idioma fijo: con "auto", Whisper adivina el idioma de cada tramo y sobre
    # ruido escribe en árabe o en inglés.
    language = meeting.language if meeting.language and meeting.language != "auto" else "es"
    # Control de ritmo: cuánto audio llegó desde que empezó a llegar.
    audio_started_at: float | None = None
    audio_received_ms = 0
    rate_warned = False
    # Audio de trabajo de la reunión: se abre con el primer audio que llega.
    writer: PcmWriter | None = None
    # False = el recorder transcribe en su máquina (bridge) y manda audio solo
    # para grabar.
    transcribe = True
    # Horas de audio del mes (§2.2): pasado el tope, se graba sin transcribir.
    audio_guard = plans.AudioGuard(meeting.id, meeting.organization_id, user.id)
    # Plan Gratis: reuniones de hasta una hora (aviso a los 55 minutos).
    free_limit = False
    base_audio_ms = 0
    hour_warned = False
    hour_reached = False

    async def forward_bus():
        try:
            while True:
                message = await queue.get()
                await websocket.send_text(json.dumps(message))
        except Exception:
            pass

    forward_task = asyncio.create_task(forward_bus())

    # Los tramos se transcriben en orden en una tarea aparte: si el loop que
    # recibe el audio esperaba cada llamada al STT, mientras tanto no leía nada
    # (ni los pings del WebSocket) y una llamada lenta cortaba la conexión.
    jobs: asyncio.Queue[tuple[bytes, int, bool]] = asyncio.Queue()

    def take_chunk(final: bool = False, upto: int | None = None) -> None:
        """Saca el tramo del buffer (hasta el corte) y lo encola para transcribir."""
        nonlocal audio_buffer, stream_offset_ms
        if not audio_buffer or stt_provider is None:
            audio_buffer = bytearray()
            return
        # Hasta el corte elegido; lo que sigue queda para el próximo tramo.
        cut = len(audio_buffer) if upto is None else upto
        chunk = bytes(audio_buffer[:cut])
        audio_buffer = audio_buffer[cut:]
        duration_ms = int(len(chunk) / 2 / channels / sample_rate * 1000)
        offset = stream_offset_ms
        stream_offset_ms += duration_ms
        jobs.put_nowait((chunk, offset, final))

    async def transcribe_chunk(chunk: bytes, offset: int, final: bool) -> None:
        nonlocal stt_error_sent, segments_since_insights, previous_text
        mic_track: bytes | None = None
        system_track: bytes | None = None
        tracks = [chunk]
        if channels == 2:
            mic_track, system_track = split_channels(chunk)
            chunk = downmix(mic_track, system_track)
            # Cada canal por separado: al mezclar, una voz que está en uno
            # solo queda a la mitad de volumen.
            tracks = [mic_track, system_track]

        if not await audio_guard.allowed(offset):
            if not audio_guard.warned:
                audio_guard.warned = True
                await live_bus.publish(
                    channel, {"type": "warning", "code": "audio_limit", "message": plans.AUDIO_LIMIT_MESSAGE}
                )
            return
        # Whisper alucina créditos de subtitulado sobre silencio; además una
        # llamada por ventana muda es gasto puro.
        if all(is_silent(track, sample_rate) for track in tracks):
            del chunk
            return
        # Un error suelto (timeout, 5xx, rate limit) se reintenta con espera:
        # sin eso el tramo se perdía entero. Si Groq sigue caído, el tramo no
        # se pierde igual: está en el audio de trabajo y la pasada final lo
        # transcribe (o lo guarda para reintentar, services/diarization.py).
        # Sin lo último dicho como pista, solo el diccionario: en un tramo casi
        # mudo el modelo devolvía la pista tal cual (el turno gigante de las
        # 02:10 de la reunión eb3ce903), y con pista "uno dos tres probando"
        # salía 12 veces en vez de 5 (bench/casos/2026-09-30).
        result = None
        for attempt, wait in enumerate((*LIVE_RETRY_WAITS, None)):
            try:
                result = await stt_provider.transcribe_chunk(
                    chunk, sample_rate, language, vocabulary, offset_ms=offset
                )
                break
            except Exception as exc:  # provider caído: avisar sin matar la reunión
                log.warning("stt cloud error (intento %d): %s", attempt + 1, exc)
                if wait is not None:
                    await asyncio.sleep(wait)
        del chunk  # descartar el audio explícitamente
        if result is None:
            if not stt_error_sent:
                stt_error_sent = True
                await live_bus.publish(
                    channel,
                    {
                        "type": "warning",
                        "code": "stt_error",
                        "message": "La transcripción en vivo se demora. El audio se sigue guardando y "
                        "se transcribe completo al finalizar.",
                    },
                )
            return
        stt_error_sent = False
        await _record_live_usage(meeting, user.id, stt_provider, len(tracks[0]) / 2 / sample_rate)
        for seg in result.segments:
            text = strip_hallucinations(seg.text)
            if (
                not text
                or is_unreliable(seg)
                or is_prompt_echo(text, vocabulary)
                or is_noise_transcript(text, language)
                or repeats_previous(text, previous_text)
            ):
                continue
            speaker = seg.speaker
            if mic_track is not None and system_track is not None:
                # La energía de canal manda sobre la etiqueta del modelo: es
                # medición y se mantiene estable entre chunks.
                speaker = (
                    attribute_speaker(
                        mic_track,
                        system_track,
                        seg.start_ms - offset,
                        seg.end_ms - offset,
                        sample_rate,
                    )
                    or speaker
                )
            event = await _store_segment(meeting, text, seg.start_ms, seg.end_ms, seg.confidence, speaker)
            await live_bus.publish(channel, event)
            previous_text = text
            segments_since_insights += 1
        if segments_since_insights >= 8 or (final and segments_since_insights > 0):
            segments_since_insights = 0
            spawn(maybe_extract_live_insights(str(meeting.id)), name=f"insights:{meeting.id}")

    async def transcriber() -> None:
        while True:
            chunk, offset, final = await jobs.get()
            try:
                await transcribe_chunk(chunk, offset, final)
            except Exception as exc:  # noqa: BLE001 - un tramo no corta la reunión
                log.warning("live %s: tramo sin transcribir: %s", meeting.id, exc)
            finally:
                jobs.task_done()

    transcriber_task = asyncio.create_task(transcriber())

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                # Audio PCM16 (modo cloud). Solo el recorder puede mandarlo.
                if role != "recorder":
                    continue
                now = asyncio.get_running_loop().time()
                if audio_started_at is None:
                    audio_started_at = now
                audio_received_ms += int(len(message["bytes"]) / 2 / channels / sample_rate * 1000)
                if free_limit:
                    total_ms = base_audio_ms + audio_received_ms
                    if total_ms >= plans.FREE_MEETING_SECONDS * 1000:
                        if not hour_reached:
                            hour_reached = True
                            await websocket.send_text(json.dumps({
                                "type": "limit", "code": "meeting_length",
                                "message": "En el plan Gratis las reuniones duran hasta una hora: la grabación se "
                                "terminó y Echo ya está armando el acta.",
                            }))
                        continue
                    if not hour_warned and total_ms >= plans.FREE_MEETING_WARN_SECONDS * 1000:
                        hour_warned = True
                        await live_bus.publish(channel, {
                            "type": "warning", "code": "meeting_length",
                            "message": "Quedan 5 minutos: en el plan Gratis las reuniones duran hasta una hora.",
                        })
                elapsed_ms = (now - audio_started_at) * 1000
                if not rate_warned and elapsed_ms > 5000 and audio_received_ms > elapsed_ms * MAX_REALTIME_RATIO:
                    rate_warned = True
                    log.warning(
                        "live %s: llega %.1fx más audio que el tiempo real (¿dos micrófonos?)",
                        meeting.id, audio_received_ms / elapsed_ms,
                    )
                if writer is None and sample_rate == 16000:
                    # Los tiempos arrancan donde termina el audio ya guardado
                    # de esta reunión (reconexión, pausa y reanudar).
                    existing = pcm_path(meeting.id)
                    stream_offset_ms = existing.stat().st_size // 32 if existing.exists() else 0
                    writer = PcmWriter(meeting.id)
                if writer is not None:
                    writer.write(message["bytes"], channels)
                if not transcribe:
                    continue
                if stt_provider is None:
                    async with SessionLocal() as db:
                        config = await resolve_stt(db, meeting.organization_id)
                        vocabulary = await get_vocabulary(db, meeting.organization_id)
                    if config is None:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": "stt_not_configured",
                                    "message": "No hay motor de transcripción cloud configurado. Configurá uno en Ajustes → IA o usá Echo Bridge.",
                                }
                            )
                        )
                        continue
                    # Sin respaldo en otro proveedor (OpenAI no recibe audio): si Groq
                    # no responde, se reintenta y el tramo sale en la pasada final.
                    stt_provider = get_stt_provider(config.provider, config.api_key, config.model)
                audio_buffer.extend(message["bytes"])
                cut = find_cut(bytes(audio_buffer), sample_rate, channels)
                if cut:
                    take_chunk(upto=cut)
                continue

            raw = message.get("text")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = data.get("type")

            if msg_type == "hello":
                requested = data.get("role", "viewer")
                role = "recorder" if requested == "recorder" else "viewer"
                if role == "recorder" and data.get("channels"):
                    try:
                        channels = 2 if int(data["channels"]) == 2 else 1
                    except (TypeError, ValueError):
                        channels = 1
                if role == "recorder" and data.get("sample_rate"):
                    with contextlib.suppress(ValueError, TypeError):
                        sample_rate = max(8000, min(48000, int(data["sample_rate"])))
                if role == "recorder":
                    async with SessionLocal() as db:
                        org = await db.get(Organization, meeting.organization_id)
                        free_limit = not plans.is_paid(org, user)
                    existing = pcm_path(meeting.id)
                    base_audio_ms = existing.stat().st_size // 32 if existing.exists() else 0
                    previous = _recorders.get(channel)
                    if previous is not None and previous is not websocket:
                        with contextlib.suppress(Exception):
                            await previous.close(code=4409, reason="Otra grabadora tomó la reunión")
                    _recorders[channel] = websocket
                    transcribe = data.get("transcribe", True) is not False
                    # Se relee: la grabación se pudo activar después de abrir el WS.
                    async with SessionLocal() as db:
                        fresh = await db.get(Meeting, meeting.id)
                        recording = fresh.recording if fresh else None
                    if is_enabled(recording) and recording.get("status") != "recording":
                        await update_state(meeting.id, status="recording")
                await websocket.send_text(
                    json.dumps({"type": "hello_ack", "role": role, "meeting_status": meeting.status})
                )

            elif msg_type == "partial" and role == "recorder":
                # texto parcial efímero: broadcast, no se persiste
                await live_bus.publish(
                    channel,
                    {
                        "type": "partial",
                        "text": str(data.get("text", ""))[:MAX_SEGMENT_CHARS],
                        "start_ms": int(data.get("start_ms", 0) or 0),
                        "speaker_hint": data.get("speaker_hint"),
                    },
                )

            elif msg_type == "segment" and role == "recorder":
                # texto final desde el bridge (modo local): persistir + broadcast
                text = str(data.get("text", "")).strip()
                if not text:
                    continue
                event = await _store_segment(
                    meeting,
                    text,
                    int(data.get("start_ms", 0) or 0),
                    int(data.get("end_ms", 0) or 0),
                    data.get("confidence"),
                    data.get("speaker_hint"),
                )
                await live_bus.publish(channel, event)
                segments_since_insights += 1
                if segments_since_insights >= 8:
                    segments_since_insights = 0
                    spawn(maybe_extract_live_insights(str(meeting.id)), name=f"insights:{meeting.id}")

            elif msg_type == "flush" and role == "recorder":
                # Pausa o fin: se transcribe lo que quedaba y recién entonces se
                # avisa. Al finalizar, el navegador espera este aviso antes de
                # pedir el procesamiento; si no, el acta arrancaba sin el
                # último tramo.
                take_chunk(final=True)
                await jobs.join()
                if writer is not None:
                    writer.flush()
                await websocket.send_text(json.dumps({"type": "flushed"}))

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("live ws error: %s", exc)
    finally:
        # flush final de audio pendiente para no perder los últimos segundos
        with contextlib.suppress(Exception):
            take_chunk(final=True)
            await jobs.join()
        transcriber_task.cancel()
        if writer is not None:
            writer.close()
        if _recorders.get(channel) is websocket:
            _recorders.pop(channel, None)
        forward_task.cancel()
        await live_bus.unsubscribe(channel, queue)
