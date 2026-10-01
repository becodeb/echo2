"""Pasada final: la reunión entera, transcripta de nuevo y (si corresponde) con quién habló.

En vivo el audio va en tramos cortos; al finalizar se escucha el audio de
trabajo completo (services/recording.py), que tiene más contexto, y su
resultado reemplaza al texto en vivo. Una sola fuente por reunión
(docs/plan-transcripcion-y-planes.md, §3):

- **Con personas** (plan de la organización, plan individual o un crédito;
  services/plans.py): ElevenLabs Scribe v2 sobre el audio entero. Cada
  palabra trae su tiempo y su persona, así que texto y personas salen del
  MISMO resultado y los turnos se arman de las palabras. Ninguna palabra
  queda sin persona. Después, services/speaker_names.py pone los nombres: lo
  que cada uno dijo ("hola, soy...") y su voz comparada con "Mi voz".
- **Sin personas** (Base sin pedirlo, sin créditos, o con menores de 18):
  Groq whisper-large-v3-turbo sobre el audio entero, en partes de 10 min.

Antes se mezclaban dos transcripciones (texto de gpt-4o-transcribe con las
voces de gpt-4o-transcribe-diarize) y una "red de seguridad" agregaba frases
que solo había oído la separación: dejaba duplicados y turnos "Hablante"
sin persona (reunión eb3ce903). Eso ya no existe.

Respaldo: si ElevenLabs falla (caída, sin cuota), el texto sale de Groq, la
reunión queda con "personas pendientes" y `retry_pending_people` vuelve a
intentar más tarde con una copia comprimida del audio. No se etiqueta mal:
mientras tanto, no hay personas.

Si el que falla es Groq, no hay otro proveedor de respaldo (OpenAI no recibe
audio): queda el texto en vivo, se guarda una copia comprimida del audio
(como mucho 48 h) y `retry_pending_text` la vuelve a mandar a Groq más tarde.
Quien grabó recibe un aviso.

`name_speakers` le pide después a la IA que deduzca quién es cada persona que
siga sin nombre, con una lista cerrada de roles ("Mamá de Pedro"). Si no está
segura, queda sin nombre.
"""
import asyncio
import logging
import re
import uuid
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy import text as sql_text

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Family,
    FamilyMember,
    InternalGroup,
    Meeting,
    MeetingParticipant,
    Notification,
    Speaker,
    TranscriptSegment,
    UsageEvent,
    User,
)
from . import plans, speaker_names
from .ai_settings import get_vocabulary, resolve_stt
from .recording import pcm_path, recordings_dir
from .speaker_names import Naming
from .stt.base import (
    SCRIBE_MODEL,
    SttResult,
    SttSegment,
    get_stt_provider,
    pcm16_to_wav,
)
from .stt.channels import (
    MIC_SPEAKER,
    SYSTEM_SPEAKER,
    is_noise_transcript,
    is_unreliable,
    strip_hallucinations,
)
from .stt.elevenlabs import group_words

log = logging.getLogger("echo.diarization")

SAMPLE_RATE = 16000
BYTES_PER_MS = 32  # PCM16 mono 16 kHz
PART_MS = 10 * 60 * 1000  # 10 min de WAV ≈ 19 MB, bajo el límite de 25 MB de Groq
MIN_AUDIO_MS = 5000
MIN_PART_MS = 3000
# Reintentos de la separación cuando ElevenLabs falló.
MAX_PEOPLE_ATTEMPTS = 6
RETRY_EVERY_SECONDS = 15 * 60
SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

Row = tuple[str | None, str, int, int]  # (persona, texto, inicio, fin)


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\wáéíóúüñ ]", " ", (text or "").lower()).split())


def text_retry_path(meeting_id: uuid.UUID) -> Path:
    """Copia del audio para reintentar el texto cuando Groq no respondió."""
    return recordings_dir() / f"{meeting_id}.text.mp3"


def people_path(meeting_id: uuid.UUID) -> Path:
    """Copia comprimida del audio para reintentar la separación de personas."""
    return recordings_dir() / f"{meeting_id}.people.mp3"


# ── Turnos (puro, sin base ni red) ───────────────────────────────


def _clean_rows(segments: list[SttSegment], language: str | None) -> list[Row]:
    """Los mismos filtros que el en vivo, sobre cada turno."""
    rows: list[Row] = []
    for seg in segments:
        text = strip_hallucinations(seg.text)
        if not text or is_unreliable(seg) or is_noise_transcript(text, language):
            continue
        rows.append((seg.speaker, text, seg.start_ms, max(seg.end_ms, seg.start_ms + 1)))
    return rows


def rows_from_scribe(result: SttResult, language: str | None) -> list[Row]:
    """Turnos con persona a partir de las palabras de Scribe."""
    return _clean_rows(group_words(result.words), language)


def _pcm_array(path: Path) -> np.ndarray | None:
    """El audio de trabajo como int16 sin cargarlo entero en memoria."""
    try:
        return np.memmap(path, dtype=np.int16, mode="r") if path.stat().st_size >= 2 else None
    except (OSError, ValueError):
        return None


async def _names(meeting_id: uuid.UUID, rows: list[Row], pcm_file: Path) -> dict[str, Naming]:
    return await speaker_names.resolve(meeting_id, rows, _pcm_array(pcm_file))


# ── Llamadas a los proveedores ───────────────────────────────────


async def _encode_mp3(sources: list[Path], target: Path) -> None:
    """PCM16 mono 16 kHz (uno o varios archivos, en fila) → mp3 64 kbps."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
        "-i", "concat:" + "|".join(str(source) for source in sources),
        "-codec:a", "libmp3lame", "-b:a", "64k", str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError((stderr or b"").decode(errors="ignore")[-300:] or "ffmpeg falló")


async def _scribe(audio: Path, language: str | None, vocabulary: list[str]) -> SttResult:
    provider = get_stt_provider("elevenlabs", get_settings().elevenlabs_api_key)
    return await provider.transcribe_file(audio.read_bytes(), audio.name, language, vocabulary)


def _part_ranges(handle, size: int) -> list[tuple[int, int]]:
    """Partes de ~10 min cortadas en el momento más callado cerca del límite."""
    ranges = []
    start = 0
    part_bytes = PART_MS * BYTES_PER_MS
    search = 8000 * BYTES_PER_MS
    while start < size:
        end = min(size, start + part_bytes)
        if size - end < MIN_PART_MS * BYTES_PER_MS:
            end = size
        elif end < size:
            handle.seek(end - search)
            window = handle.read(search)
            samples = np.frombuffer(window[: len(window) // 2 * 2], dtype=np.int16).astype(np.float32)
            frames = len(samples) // 1600
            if frames:
                rms = np.sqrt((samples[: frames * 1600].reshape(frames, 1600) ** 2).mean(axis=1))
                end = end - search + int(np.argmin(rms)) * 1600 * 2
        if end - start >= MIN_PART_MS * BYTES_PER_MS:
            ranges.append((start, end))
        start = end
    return ranges


def _text_engine(config):
    """El motor de la pasada sin personas: Groq, sin respaldo en otro proveedor."""
    groq = _groq_key(config)
    return get_stt_provider("groq", groq) if groq else None


async def _text_rows(path: Path, provider, language: str | None, vocabulary: list[str]) -> list[Row]:
    """Texto sin personas de la reunión entera, parte por parte."""
    rows: list[Row] = []
    with open(path, "rb") as handle:
        for start, end in _part_ranges(handle, path.stat().st_size):
            handle.seek(start)
            wav = pcm16_to_wav(handle.read(end - start), SAMPLE_RATE)
            result = await provider.transcribe_file(wav, "reunion.wav", language, vocabulary)
            offset = start // BYTES_PER_MS
            for speaker, text, begin, finish in _clean_rows(result.segments, language):
                rows.append((speaker, text, begin + offset, min(finish + offset, end // BYTES_PER_MS)))
    return rows


def _groq_key(config) -> str:
    if config is not None and config.provider == "groq":
        return config.api_key
    return get_settings().groq_api_key


async def _vocabulary(db, meeting: Meeting) -> list[str]:
    """Diccionario de la sede + nombres de quienes están en la reunión."""
    terms = list(await get_vocabulary(db, meeting.organization_id))
    participants = (
        (await db.execute(select(MeetingParticipant.name).where(MeetingParticipant.meeting_id == meeting.id)))
        .scalars()
        .all()
    )
    terms += [name for name in participants if name]
    creator = await db.get(User, meeting.created_by)
    if creator and creator.name:
        terms.append(creator.name)
    if meeting.family_id:
        family = await db.get(Family, meeting.family_id)
        if family:
            terms.append(family.name)
        terms += (
            (await db.execute(select(FamilyMember.name).where(FamilyMember.family_id == meeting.family_id)))
            .scalars()
            .all()
        )
    return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))


# ── Orquestación ─────────────────────────────────────────────────


async def _live_rows(meeting_id: uuid.UUID) -> list[tuple[int, int, str, str | None]]:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    TranscriptSegment.start_ms,
                    TranscriptSegment.end_ms,
                    TranscriptSegment.text,
                    TranscriptSegment.speaker_hint,
                )
                .where(TranscriptSegment.meeting_id == meeting_id)
                .order_by(TranscriptSegment.seq)
            )
        ).all()
    return [(start, end, text, hint) for start, end, text, hint in rows if (text or "").strip()]


async def _update_meta(meeting_id: uuid.UUID, **changes) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return
        meta = {**(meeting.meta or {})}
        for key, value in changes.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        meeting.meta = meta
        await db.commit()


async def diarize_meeting(meeting_id: uuid.UUID) -> bool:
    """Pasada final. True = el transcript quedó con sus personas.

    False = no hubo separación (sigue la consolidación de siempre sobre lo que
    haya): el texto puede igual haberse reemplazado por el de Groq.
    """
    path = pcm_path(meeting_id)
    if not path.exists() or path.stat().st_size < MIN_AUDIO_MS * BYTES_PER_MS:
        return False
    total_ms = path.stat().st_size // BYTES_PER_MS
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return False
        organization_id, created_by = meeting.organization_id, meeting.created_by
        if (meeting.meta or {}).get("audio_limit"):
            # Se pasó de las horas de audio del mes: queda lo transcripto en vivo.
            return False
        # Decidir y reservar los créditos van juntos y de a una reunión por
        # persona: si le queda 1 crédito y terminan dos reuniones a la vez,
        # solo una lo gasta (la otra sale sin personas).
        if created_by is not None:  # las de un Echo Device no tienen persona
            await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(created_by)})
        decision = await plans.final_pass_for(db, meeting, total_ms / 1000)
        hold_id = None
        if decision.provider == "elevenlabs" and decision.credits:
            hold = await plans.record_usage(
                db, kind="stt_final", provider="elevenlabs", model=SCRIBE_MODEL, unit="audio_seconds",
                quantity=0, cost_usd=0, organization_id=organization_id, user_id=created_by,
                meeting_id=meeting_id, credits=decision.credits,
                meta={"covered_by": decision.covered_by, "hold": True},
            )
            await db.flush()
            hold_id = hold.id
        await db.commit()
        config = await resolve_stt(db, meeting.organization_id)
        vocabulary = await _vocabulary(db, meeting)
        language = meeting.language if meeting.language and meeting.language != "auto" else "es"

    live = await _live_rows(meeting_id)
    # Lo dicho después del audio de trabajo (se grabó solo una parte con el
    # bridge, o se retomó otro día) no está en el audio: se conserva, sin
    # persona (sus etiquetas del en vivo no son las de la pasada final).
    after = _after_audio(live, total_ms)

    if decision.provider == "elevenlabs":
        rows = await _people_pass(
            meeting_id, path, language, vocabulary, decision, organization_id, created_by, total_ms, hold_id
        )
        if rows is not None:
            await _replace_transcript(meeting_id, rows + after, await _names(meeting_id, rows, path))
            return True

    # Sin personas (o ElevenLabs falló): texto de Groq, sin etiquetar a nadie.
    if any(hint in (MIC_SPEAKER, SYSTEM_SPEAKER) for _, _, _, hint in live):
        # Llamada de Meet/Zoom: el en vivo ya separó micrófono y sistema por
        # canal, y el audio de trabajo está mezclado. Se queda el en vivo.
        return False
    engine = _text_engine(config)
    if engine is None:
        return False
    try:
        rows = await _text_rows(path, engine, language, vocabulary)
    except Exception as exc:  # noqa: BLE001 - queda el transcript en vivo
        log.warning("pasada final sin personas falló en %s: %s", meeting_id, exc)
        await _keep_for_text_retry(meeting_id, path, total_ms, decision.reason)
        return False
    await _record_text_usage(engine, total_ms, organization_id, created_by, meeting_id, decision.reason)
    if rows:
        await _replace_transcript(meeting_id, [(None, line, start, end) for _, line, start, end in rows] + after, {})
    return False


async def _record_text_usage(engine, total_ms: int, organization_id, created_by, meeting_id, reason) -> None:
    name, model = engine.name, getattr(engine, "model", None)
    async with SessionLocal() as db:
        await plans.record_usage(
            db, kind="stt_final", provider=name, model=model, unit="audio_seconds",
            quantity=total_ms / 1000, cost_usd=plans.stt_cost(name, model, total_ms / 1000),
            organization_id=organization_id, user_id=created_by, meeting_id=meeting_id,
            meta={"reason": reason},
        )
        await db.commit()


async def _notify_creator(meeting_id: uuid.UUID, title: str, body: str) -> None:
    """Aviso en la campanita de quien grabó (las de un Echo Device no tienen persona)."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or meeting.created_by is None:
            return
        db.add(
            Notification(
                user_id=meeting.created_by, organization_id=meeting.organization_id, kind="transcript_status",
                title=title[:300], body=body, link=f"/meetings/{meeting_id}",
            )
        )
        await db.commit()


async def _keep_for_text_retry(meeting_id: uuid.UUID, path: Path, total_ms: int, reason: str | None) -> None:
    """Groq no respondió: se guarda el audio comprimido para reintentar.

    Si ElevenLabs también quedó pendiente, su reintento ya trae el texto: no
    hace falta otra copia.
    """
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or (meeting.meta or {}).get("people_status") == "pending":
            return
    target = text_retry_path(meeting_id)
    try:
        await _encode_mp3([path], target)
    except Exception as exc:  # noqa: BLE001 - sin copia queda el texto en vivo
        log.warning("no se pudo guardar el audio de %s para reintentar el texto: %s", meeting_id, exc)
        target.unlink(missing_ok=True)
        return
    await _update_meta(
        meeting_id, text_status="pending", text_retry={"total_ms": total_ms, "attempts": 1, "reason": reason}
    )
    await _notify_creator(
        meeting_id,
        "La transcripción completa se demora",
        "El servicio de transcripción no respondió. Por ahora queda el texto en vivo; Echo lo vuelve a "
        "intentar solo y te avisa. El audio se guarda como mucho 48 horas.",
    )


async def _decode_mp3(source: Path, target: Path) -> None:
    """mp3 → PCM16 mono 16 kHz, lo que lee `_text_rows`."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError((stderr or b"").decode(errors="ignore")[-300:] or "ffmpeg falló")


async def retry_pending_text() -> int:
    """Vuelve a mandar a Groq las reuniones cuyo texto quedó pendiente.

    Como con las personas: si alguien corrigió el transcript a mano, no se pisa.
    """
    done = 0
    async with SessionLocal() as db:
        pending = (
            (
                await db.execute(
                    select(Meeting).where(
                        Meeting.deleted_at.is_(None),
                        Meeting.status == "completed",
                        Meeting.meta["text_status"].astext == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        jobs = [
            (m.id, m.organization_id, m.created_by, m.language, dict((m.meta or {}).get("text_retry") or {}))
            for m in pending
        ]
    for meeting_id, organization_id, created_by, language, retry in jobs:
        audio = text_retry_path(meeting_id)
        if not audio.exists() or not retry:
            await _update_meta(meeting_id, text_status="failed", text_retry=None)
            continue
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            vocabulary = await _vocabulary(db, meeting) if meeting else []
            config = await resolve_stt(db, organization_id)
        engine = _text_engine(config)
        language = language if language and language != "auto" else "es"
        pcm = audio.with_name(f"{meeting_id}.text.pcm")
        try:
            if engine is None:
                raise RuntimeError("sin key de Groq")
            await _decode_mp3(audio, pcm)
            rows = await _text_rows(pcm, engine, language, vocabulary)
        except Exception as exc:  # noqa: BLE001 - se vuelve a intentar en la próxima vuelta
            attempts = int(retry.get("attempts") or 1) + 1
            log.warning("reintento de texto %s/%s falló en %s: %s", attempts, MAX_PEOPLE_ATTEMPTS, meeting_id, exc)
            if attempts >= MAX_PEOPLE_ATTEMPTS:
                audio.unlink(missing_ok=True)
                await _update_meta(meeting_id, text_status="failed", text_retry=None)
                await _notify_creator(
                    meeting_id,
                    "No se pudo completar la transcripción",
                    "Quedó el texto que se tomó en vivo. El audio guardado para reintentar ya se borró.",
                )
            else:
                await _update_meta(meeting_id, text_retry={**retry, "attempts": attempts})
            continue
        finally:
            pcm.unlink(missing_ok=True)
        audio.unlink(missing_ok=True)
        total_ms = int(retry.get("total_ms") or 0)
        await _record_text_usage(engine, total_ms, organization_id, created_by, meeting_id, retry.get("reason"))
        after = _after_audio(await _live_rows(meeting_id), total_ms)
        final = [(None, line, start, end) for _, line, start, end in rows] + after
        if not rows or not await _replace_transcript(meeting_id, final, {}, only_if_unedited=True):
            await _update_meta(meeting_id, text_status="skipped", text_retry=None)
            continue
        await _update_meta(meeting_id, text_status="done", text_retry=None)
        await _after_retry(meeting_id, organization_id, created_by)
        await _notify_creator(
            meeting_id, "La transcripción completa ya está", "Se reemplazó el texto en vivo por la versión completa."
        )
        done += 1
    return done


def _lock_key(user_id: uuid.UUID) -> int:
    """Clave de pg_advisory_xact_lock (bigint) para los créditos de una persona."""
    return user_id.int % (2**63 - 1)


def _after_audio(live: list[tuple[int, int, str, str | None]], total_ms: int) -> list[Row]:
    return [(None, line, start, end) for start, end, line, _ in live if start >= total_ms]


async def _release_hold(hold_id: str | uuid.UUID | None) -> None:
    """La separación no salió: los créditos reservados vuelven."""
    if not hold_id:
        return
    async with SessionLocal() as db:
        await db.execute(delete(UsageEvent).where(UsageEvent.id == uuid.UUID(str(hold_id))))
        await db.commit()


async def _people_pass(
    meeting_id: uuid.UUID,
    path: Path,
    language: str,
    vocabulary: list[str],
    decision: "plans.FinalPass",
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    total_ms: int,
    hold_id: uuid.UUID | None = None,
) -> list[Row] | None:
    """Scribe sobre la reunión entera.

    None = no hay personas: falló y quedó pendiente de reintento (con los
    créditos reservados), o no se pudo / no devolvió nada (créditos devueltos).
    """
    audio = people_path(meeting_id)
    try:
        await _encode_mp3([path], audio)
    except Exception as exc:  # noqa: BLE001 - sin mp3 no hay pasada con personas
        log.warning("no se pudo preparar el audio de %s para ElevenLabs: %s", meeting_id, exc)
        audio.unlink(missing_ok=True)
        await _release_hold(hold_id)
        return None

    retry = {
        "credits": decision.credits,
        "covered_by": decision.covered_by,
        "total_ms": total_ms,
        "attempts": 1,
        "hold_id": str(hold_id) if hold_id else None,
    }
    try:
        result = await _scribe(audio, language, vocabulary)
    except Exception as exc:  # noqa: BLE001 - respaldo: Groq ahora, personas después
        log.warning("ElevenLabs falló en %s, queda pendiente: %s", meeting_id, exc)
        await _update_meta(meeting_id, people_status="pending", people_retry=retry)
        return None
    audio.unlink(missing_ok=True)
    rows = rows_from_scribe(result, language)
    if not rows:
        # Scribe no oyó nada: no se borra el texto en vivo ni se cobra.
        log.warning("ElevenLabs devolvió una transcripción vacía en %s", meeting_id)
        await _release_hold(hold_id)
        await _update_meta(meeting_id, people_status="failed", people_retry=None)
        return None
    await _charge(meeting_id, organization_id, created_by, retry, result)
    return rows


async def _charge(
    meeting_id: uuid.UUID, organization_id: uuid.UUID, created_by: uuid.UUID, retry: dict, result: SttResult
) -> None:
    """Anota el consumo y los créditos (solo cuando la separación salió bien).

    Los créditos ya estaban reservados al decidir: la reserva pasa a ser el consumo.
    """
    seconds = (retry["total_ms"] + int(retry.get("offset_ms") or 0)) / 1000
    cost = plans.stt_cost("elevenlabs", SCRIBE_MODEL, seconds, keyterms=True, entities=True)
    async with SessionLocal() as db:
        hold = await db.get(UsageEvent, uuid.UUID(retry["hold_id"])) if retry.get("hold_id") else None
        if hold is not None:
            hold.quantity = float(seconds)
            hold.cost_usd = cost
            hold.meta = {"covered_by": retry.get("covered_by")}
        else:
            await plans.record_usage(
                db, kind="stt_final", provider="elevenlabs", model=SCRIBE_MODEL, unit="audio_seconds",
                quantity=seconds, cost_usd=cost,
                organization_id=organization_id, user_id=created_by, meeting_id=meeting_id,
                credits=retry.get("credits") or 0, meta={"covered_by": retry.get("covered_by")},
            )
        meeting = await db.get(Meeting, meeting_id)
        if meeting is not None:
            meta = {**(meeting.meta or {})}
            meta.pop("people_retry", None)
            meta["people_status"] = "done"
            # Nombres y datos que Scribe detectó: se seudonimizan antes de la IA
            # (services/privacy.py), aunque no estén en ninguna nómina.
            meta["detected_entities"] = [
                {"text": entity.text, "type": entity.entity_type} for entity in result.entities
            ][:200]
            meeting.meta = meta
        await db.commit()


async def retry_pending_people() -> int:
    """Vuelve a pedir la separación de las reuniones que quedaron pendientes.

    Si alguien ya corrigió el transcript a mano (antes o mientras ElevenLabs
    procesaba), no se pisa: se da por terminado sin personas y sin cobrar.
    Si sale bien, la IA vuelve a deducir los nombres y la reunión se vuelve a
    indexar para el chat.
    """
    done = 0
    async with SessionLocal() as db:
        pending = (
            (
                await db.execute(
                    select(Meeting).where(
                        Meeting.deleted_at.is_(None),
                        Meeting.status == "completed",
                        Meeting.meta["people_status"].astext == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        jobs = [(m.id, m.organization_id, m.created_by, m.language, dict((m.meta or {}).get("people_retry") or {})) for m in pending]
    for meeting_id, organization_id, created_by, language, retry in jobs:
        audio = people_path(meeting_id)
        if not audio.exists() or not retry:
            await _release_hold(retry.get("hold_id"))
            await _update_meta(meeting_id, people_status="failed", people_retry=None)
            continue
        async with SessionLocal() as db:
            edited = (
                await db.execute(
                    select(TranscriptSegment.id).where(
                        TranscriptSegment.meeting_id == meeting_id, TranscriptSegment.edited.is_(True)
                    ).limit(1)
                )
            ).first()
            meeting = await db.get(Meeting, meeting_id)
            vocabulary = await _vocabulary(db, meeting) if meeting else []
        if edited:
            audio.unlink(missing_ok=True)
            await _release_hold(retry.get("hold_id"))
            await _update_meta(meeting_id, people_status="skipped", people_retry=None)
            continue
        language = language if language and language != "auto" else "es"
        try:
            result = await _scribe(audio, language, vocabulary)
        except Exception as exc:  # noqa: BLE001 - se vuelve a intentar en la próxima vuelta
            attempts = int(retry.get("attempts") or 1) + 1
            log.warning("reintento de personas %s/%s falló en %s: %s", attempts, MAX_PEOPLE_ATTEMPTS, meeting_id, exc)
            if attempts >= MAX_PEOPLE_ATTEMPTS:
                audio.unlink(missing_ok=True)
                await _release_hold(retry.get("hold_id"))
                await _update_meta(meeting_id, people_status="failed", people_retry=None)
            else:
                await _update_meta(meeting_id, people_retry={**retry, "attempts": attempts})
            continue
        rows = rows_from_scribe(result, language)
        if not rows:
            audio.unlink(missing_ok=True)
            await _release_hold(retry.get("hold_id"))
            await _update_meta(meeting_id, people_status="failed", people_retry=None)
            continue
        # Los nombres por voz necesitan el audio: se descomprime la copia, se
        # usa y se borra junto con ella.
        pcm = audio.with_name(f"{meeting_id}.people.pcm")
        try:
            await _decode_mp3(audio, pcm)
            names = await _names(meeting_id, rows, pcm)
        except Exception as exc:  # noqa: BLE001 - sin nombres por voz, sigue igual
            log.warning("sin nombres por voz en el reintento de %s: %s", meeting_id, exc)
            names = {}
        finally:
            pcm.unlink(missing_ok=True)
            audio.unlink(missing_ok=True)
        after = _after_audio(await _live_rows(meeting_id), int(retry.get("total_ms") or 0))
        if not await _replace_transcript(meeting_id, rows + after, names, only_if_unedited=True):
            # Lo corrigieron a mano mientras ElevenLabs procesaba.
            await _release_hold(retry.get("hold_id"))
            await _update_meta(meeting_id, people_status="skipped", people_retry=None)
            continue
        await _charge(meeting_id, organization_id, created_by, retry, result)
        await _after_retry(meeting_id, organization_id, created_by)
        done += 1
    return done


async def _after_retry(meeting_id: uuid.UUID, organization_id: uuid.UUID, created_by: uuid.UUID) -> None:
    """Lo que la pasada de la reunión hizo sobre el transcript viejo, de nuevo
    sobre el nuevo: nombres deducidos por la IA e índice del chat."""
    from .ai_settings import resolve_embeddings, resolve_llm
    from .llm import get_llm_provider
    from .privacy import protect
    from .rag import embed_meeting_segments

    async with SessionLocal() as db:
        llm_config = await resolve_llm(db, organization_id)
        embeddings_config = await resolve_embeddings(db, organization_id)
        provider = None
        if llm_config:
            provider = get_llm_provider(llm_config.provider, llm_config.api_key, llm_config.model, llm_config.base_url)
            provider = await protect(db, organization_id, provider, meeting_id, created_by)
    if provider is not None:
        try:
            await name_speakers(meeting_id, provider)
        except Exception as exc:  # noqa: BLE001 - sin nombres queda "Persona 1"
            log.warning("nombres tras el reintento fallaron en %s: %s", meeting_id, exc)
    if embeddings_config:
        try:
            await embed_meeting_segments(meeting_id, embeddings_config)
        except Exception as exc:  # noqa: BLE001 - el chat queda con el índice viejo
            log.warning("índice tras el reintento falló en %s: %s", meeting_id, exc)


async def retry_loop(interval_seconds: int = RETRY_EVERY_SECONDS) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            retried = await retry_pending_people()
            if retried:
                log.info("personas: %s reuniones separadas en un reintento", retried)
        except Exception:  # noqa: BLE001 - el reintento nunca tira abajo la API
            log.exception("personas: falló el reintento")
        try:
            retried = await retry_pending_text()
            if retried:
                log.info("texto: %s reuniones transcriptas en un reintento", retried)
        except Exception:  # noqa: BLE001
            log.exception("texto: falló el reintento")


async def _replace_transcript(
    meeting_id: uuid.UUID, final: list[Row], names: dict[str, Naming], only_if_unedited: bool = False
) -> bool:
    """Reemplaza el transcript en vivo por el final, con sus personas.

    only_if_unedited: no reemplaza (y devuelve False) si alguien corrigió algún
    tramo. Los tramos quedan bloqueados mientras tanto, así una corrección que
    llega justo ahora espera y no se pierde en silencio.
    """
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return False
        if only_if_unedited:
            edited = (
                await db.execute(
                    select(TranscriptSegment.edited)
                    .where(TranscriptSegment.meeting_id == meeting_id)
                    .with_for_update()
                )
            ).scalars().all()
            if any(edited):
                return False
        await db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
        await db.execute(delete(Speaker).where(Speaker.meeting_id == meeting_id))

        speakers: dict[str, Speaker] = {}
        unnamed = 0
        for label, *_ in final:
            if label is None or label in speakers:
                continue
            naming = names.get(label)
            unnamed += 1
            accepted = naming is not None and naming.accepted
            speakers[label] = Speaker(
                meeting_id=meeting_id,
                label=f"Persona {unnamed}",
                display_name=naming.name[:200] if accepted else None,
                user_id=naming.user_id if accepted else None,
                name_source=naming.source if accepted else None,
                identity_suggestion=(
                    naming.suggestion() if naming is not None and (not accepted or naming.extra) else None
                ),
                color=SPEAKER_COLORS[len(speakers) % len(SPEAKER_COLORS)],
            )
            db.add(speakers[label])
        await db.flush()

        for seq, (label, text, start, end) in enumerate(sorted(final, key=lambda row: row[2]), start=1):
            db.add(
                TranscriptSegment(
                    meeting_id=meeting_id,
                    organization_id=meeting.organization_id,
                    seq=seq,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    is_final=True,
                    speaker_hint=label,
                    speaker_id=speakers[label].id if label is not None else None,
                )
            )
        await db.commit()
        log.info("transcripción final: %s → %s tramos, %s personas", meeting_id, len(final), len(speakers))
    return True


# ── Nombres con la IA ────────────────────────────────────────────


def _mentioned(name: str, heard: set[str]) -> bool:
    """Alguna palabra del nombre (de 3+ letras) se dijo en la reunión."""
    return any(len(word) >= 3 and word in heard for word in _normalize(name).split())

# Los únicos roles que puede poner la IA (sin "persona del ambiente" ni
# "personal del colegio"): un rol inventado confunde más que "Persona 1".
ROLES = (
    "directora", "director", "vicedirectora", "vicedirector", "secretaria", "secretario",
    "coordinadora", "coordinador", "docente", "maestra", "maestro", "profesora", "profesor",
    "preceptora", "preceptor", "psicopedagoga", "psicopedagogo", "psicóloga", "psicólogo",
    "orientadora", "orientador", "fonoaudióloga", "acompañante terapéutica", "madre", "padre",
    "tutora", "tutor", "abuela", "abuelo", "alumna", "alumno",
)
_ROLE = re.compile(
    r"^(?:(?:" + "|".join(ROLES) + r")(?: de [a-záéíóúñ]+)?|(?:mamá|papá|madre|padre|abuela|abuelo|tutora|tutor|"
    r"hermana|hermano) de .{2,60})$",
    re.IGNORECASE,
)

NAMING_SYSTEM = f"""Identificás a las personas que hablan en la transcripción de una reunión de un colegio.
Usá solo lo que surge de la conversación y del contexto. Nunca inventes nombres: si nadie dice
cómo se llama una persona y no es inequívoco por el contexto, dejá "name" en null.
"role" tiene que ser uno de estos, o null si no es claro: {", ".join(ROLES)}; también
"<rol> de <materia o nombre>" (maestra de inglés, mamá de [ALUMNO_1]). Nunca otro rol.
Si no estás seguro, null en los dos."""


async def name_speakers(meeting_id: uuid.UUID, provider) -> int:
    """Le pone nombre o rol a las personas sin nombre. Devuelve cuántas nombró."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        speakers = (
            (await db.execute(select(Speaker).where(Speaker.meeting_id == meeting_id))).scalars().all()
        )
        pending = [speaker for speaker in speakers if not speaker.display_name]
        if meeting is None or not pending:
            return 0
        segments = (
            (
                await db.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.meeting_id == meeting_id)
                    .order_by(TranscriptSegment.seq)
                )
            )
            .scalars()
            .all()
        )
        participants = (
            (await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        creator = await db.get(User, meeting.created_by)
        context = [f"Reunión: {meeting.title}"]
        if creator:
            context.append(f"La grabó: {creator.name}")
        if participants:
            context.append(
                "Participantes anotados: "
                + ", ".join(f"{p.name}{f' ({p.role_label})' if p.role_label else ''}" for p in participants)
            )
        if meeting.family_id:
            family = await db.get(Family, meeting.family_id)
            members = (
                (await db.execute(select(FamilyMember).where(FamilyMember.family_id == meeting.family_id)))
                .scalars()
                .all()
            )
            if family:
                context.append(
                    f"Familia: {family.name}. Integrantes: "
                    + (", ".join(f"{m.name} ({m.relationship_type})" for m in members) or "sin cargar")
                )
        if meeting.group_id:
            group = await db.get(InternalGroup, meeting.group_id)
            if group:
                context.append(f"Reunión interna del grupo {group.name}")
        named = [f"{s.label} ya identificada como {s.display_name}" for s in speakers if s.display_name]
        if named:
            context.append("; ".join(named))

        heard = set(_normalize(" ".join(seg.text for seg in segments)).split())

        blocks = []
        for speaker in pending:
            lines = [seg.text for seg in segments if seg.speaker_id == speaker.id][:14]
            sample = " / ".join(lines)[:1500]
            blocks.append(f"{speaker.label}: {sample}")

    prompt = (
        "\n".join(context)
        + "\n\nLo que dijo cada persona (primeras frases):\n"
        + "\n".join(blocks)
        + '\n\nRespondé con {"speakers": [{"label": "Persona 1", "name": string|null, '
        '"role": string|null, "confidence": número entre 0 y 1}]} con una entrada por cada persona de arriba.'
    )
    result = await provider.chat_json(NAMING_SYSTEM, [{"role": "user", "content": prompt}])
    entries = result.get("speakers", []) if isinstance(result, dict) else []

    count = 0
    async with SessionLocal() as db:
        by_label = {
            speaker.label: speaker
            for speaker in (await db.execute(select(Speaker).where(Speaker.meeting_id == meeting_id))).scalars()
        }
        roles = [str(entry.get("role") or "").strip().lower() for entry in entries]
        for entry in entries:
            speaker = by_label.get(str(entry.get("label") or ""))
            if speaker is None or speaker.display_name:
                continue
            name = (entry.get("name") or "").strip() or None
            role = (entry.get("role") or "").strip() or None
            if role and not _ROLE.match(role):
                role = None
            if role and not name and roles.count(role.lower()) > 1:
                # Dos "docente" no dicen quién es quién: mejor sin nombre.
                role = None
            try:
                confidence = float(entry.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            shown = f"{name} ({role})" if name and role else (name or role)
            if not shown:
                continue
            if name and not _mentioned(name, heard):
                # Nadie dijo ese nombre: la IA lo sacó de la lista de
                # participantes, y adivinar quién es quién sale cruzado (reunión
                # 89ddbc9d: puso "Bau" a la voz de Delfi). Queda como sugerencia
                # para que la persona lo confirme con un toque.
                confidence = min(confidence, 0.74)
            if confidence >= 0.75:
                speaker.display_name = shown[:200]
                speaker.name_source = "ia"
                count += 1
            elif confidence >= 0.4 and not speaker.identity_suggestion:
                # Una sugerencia por voz vale más que la de la IA: no se pisa.
                speaker.identity_suggestion = {"person_name": shown[:200], "confidence": round(confidence, 2), "source": "ia"}
        await db.commit()
    return count
