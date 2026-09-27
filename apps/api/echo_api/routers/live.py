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
from ..models import Meeting, OrganizationMember, TranscriptSegment, User
from ..security import decode_token
from ..services.ai_settings import get_vocabulary, resolve_stt
from ..services.background import spawn
from ..services.insights_live import maybe_extract_live_insights
from ..services.live_bus import live_bus
from ..services.recording import PcmWriter, is_enabled, pcm_path, update_state
from ..services.stt import get_stt_provider
from ..services.stt.windowing import find_cut
from ..services.stt.channels import (
    attribute_speaker,
    downmix,
    is_hallucination,
    is_noise_transcript,
    is_prompt_echo,
    is_silent,
    split_channels,
)

log = logging.getLogger("echo.live")

# Grabadora activa de cada reunión (id de reunión → WebSocket).
_recorders: dict[str, WebSocket] = {}
# Audio que llega más rápido que esto respecto del tiempo real = hay más de
# una fuente mandando por la misma conexión.
MAX_REALTIME_RATIO = 1.5

router = APIRouter(tags=["live"])

MAX_SEGMENT_CHARS = 2000


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
    # Control de ritmo: cuánto audio llegó desde que empezó a llegar.
    audio_started_at: float | None = None
    audio_received_ms = 0
    rate_warned = False
    # Audio de trabajo de la reunión: se abre con el primer audio que llega.
    writer: PcmWriter | None = None
    # False = el recorder transcribe en su máquina (bridge) y manda audio solo
    # para grabar.
    transcribe = True

    async def forward_bus():
        try:
            while True:
                message = await queue.get()
                await websocket.send_text(json.dumps(message))
        except Exception:
            pass

    forward_task = asyncio.create_task(forward_bus())

    async def flush_audio(final: bool = False, upto: int | None = None):
        nonlocal audio_buffer, stream_offset_ms, stt_error_sent, segments_since_insights
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

        mic_track: bytes | None = None
        system_track: bytes | None = None
        if channels == 2:
            mic_track, system_track = split_channels(chunk)
            chunk = downmix(mic_track, system_track)

        # Whisper alucina créditos de subtitulado sobre silencio; además una
        # llamada por ventana muda es gasto puro.
        if is_silent(chunk, sample_rate):
            del chunk
            return
        try:
            result = await stt_provider.transcribe_chunk(
                chunk, sample_rate, meeting.language, vocabulary, offset_ms=offset
            )
        except Exception as exc:  # provider caído: avisar sin matar la reunión
            log.warning("stt cloud error: %s", exc)
            if not stt_error_sent:
                stt_error_sent = True
                await live_bus.publish(
                    channel,
                    {"type": "warning", "code": "stt_error", "message": "El motor de transcripción falló; reintentando"},
                )
            return
        finally:
            del chunk  # descartar el audio explícitamente
        stt_error_sent = False
        for seg in result.segments:
            if (
                is_hallucination(seg.text)
                or is_prompt_echo(seg.text, vocabulary)
                or is_noise_transcript(seg.text, meeting.language)
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
            event = await _store_segment(
                meeting, seg.text.strip(), seg.start_ms, seg.end_ms, seg.confidence, speaker
            )
            await live_bus.publish(channel, event)
            segments_since_insights += 1
        if segments_since_insights >= 8 or (final and segments_since_insights > 0):
            segments_since_insights = 0
            spawn(maybe_extract_live_insights(str(meeting.id)), name=f"insights:{meeting.id}")

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
                    stt_provider = get_stt_provider(config.provider, config.api_key, config.model)
                audio_buffer.extend(message["bytes"])
                cut = find_cut(bytes(audio_buffer), sample_rate, channels)
                if cut:
                    await flush_audio(upto=cut)
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
                await flush_audio(final=True)

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("live ws error: %s", exc)
    finally:
        # flush final de audio pendiente para no perder los últimos segundos
        with contextlib.suppress(Exception):
            await flush_audio(final=True)
        if writer is not None:
            writer.close()
        if _recorders.get(channel) is websocket:
            _recorders.pop(channel, None)
        forward_task.cancel()
        await live_bus.unsubscribe(channel, queue)
