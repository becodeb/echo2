"""Pasada final: la reunión entera, transcripta de nuevo y (si corresponde) con quién habló.

En vivo el audio va en tramos cortos; al finalizar se escucha el audio de
trabajo completo (services/recording.py), que tiene más contexto, y su
resultado reemplaza al texto en vivo. Una sola fuente por reunión
(docs/plan-transcripcion-y-planes.md, §3):

- **Con personas** (plan de la organización, plan individual o un crédito;
  services/plans.py): ElevenLabs Scribe v2 sobre el audio entero. Cada
  palabra trae su tiempo y su persona, así que texto y personas salen del
  MISMO resultado y los turnos se arman de las palabras. Ninguna palabra
  queda sin persona. Las personas del colegio que grabaron su voz (Ajustes →
  Mi voz) van delante del audio, separadas por silencios: la persona que
  Scribe oye en la muestra de alguien es ese alguien, y sale con su nombre.
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

`name_speakers` le pide después a la IA que deduzca quién es cada persona sin
nombre ("Mamá de Pedro"). Si no está segura, queda como sugerencia.
"""
import asyncio
import io
import logging
import re
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Family,
    FamilyMember,
    InternalGroup,
    Meeting,
    MeetingParticipant,
    OrganizationMember,
    Speaker,
    TranscriptSegment,
    User,
    UserVoiceSample,
)
from . import plans
from .ai_settings import get_vocabulary, resolve_stt
from .recording import pcm_path, recordings_dir
from .stt.base import (
    GROQ_MODEL,
    SCRIBE_MODEL,
    FallbackSttProvider,
    SttResult,
    SttSegment,
    SttWord,
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
# Muestras de voz conocidas delante del audio: como mucho estas, separadas
# por este silencio (así Scribe no pega dos muestras en una persona).
MAX_KNOWN_VOICES = 4
VOICE_GAP_MS = 1500
# Una persona es "la de la muestra" si ocupa al menos esto de sus palabras.
VOICE_MATCH_SHARE = 0.6
# Reintentos de la separación cuando ElevenLabs falló.
MAX_PEOPLE_ATTEMPTS = 6
RETRY_EVERY_SECONDS = 15 * 60
SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

Row = tuple[str | None, str, int, int]  # (persona, texto, inicio, fin)


@dataclass
class KnownVoice:
    label: str
    user_id: uuid.UUID
    name: str
    wav: bytes


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\wáéíóúüñ ]", " ", (text or "").lower()).split())


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


def voice_prefix(voices: list[KnownVoice]) -> tuple[bytes, list[tuple[KnownVoice, int, int]]]:
    """Las muestras de voz conocidas en fila, con silencio entre ellas.

    Devuelve el PCM a poner delante de la reunión y dónde quedó cada muestra.
    """
    gap = bytes(VOICE_GAP_MS * BYTES_PER_MS)
    pcm = bytearray()
    windows: list[tuple[KnownVoice, int, int]] = []
    for voice in voices[:MAX_KNOWN_VOICES]:
        samples = _wav_pcm(voice.wav)
        if not samples:
            continue
        pcm += gap
        start = len(pcm) // BYTES_PER_MS
        pcm += samples
        windows.append((voice, start, len(pcm) // BYTES_PER_MS))
    if windows:
        pcm += gap
    return bytes(pcm), windows


def _wav_pcm(data: bytes) -> bytes:
    """PCM16 mono 16 kHz de una muestra de voz (las guarda así routers/my_voice.py)."""
    try:
        with wave.open(io.BytesIO(data)) as reader:
            if reader.getframerate() != SAMPLE_RATE or reader.getsampwidth() != 2 or reader.getnchannels() != 1:
                return b""
            return reader.readframes(reader.getnframes())
    except (wave.Error, EOFError):
        return b""


def assign_known_voices(
    words: list[SttWord], windows: list[tuple[KnownVoice, int, int]], offset_ms: int
) -> tuple[list[SttWord], dict[str, KnownVoice]]:
    """Saca las muestras del principio y dice qué persona de Scribe es cada una.

    Una persona de Scribe es la de una muestra si la mayoría de las palabras
    dichas en esa muestra son suyas, y si no la reclamó ya otra muestra (dos
    voces parecidas pegadas en una persona no se nombran: mejor sin nombre
    que con el equivocado).
    """
    known: dict[str, KnownVoice] = {}
    claimed: set[str] = set()
    for voice, start, end in windows:
        inside = [word.speaker for word in words if start <= word.start_ms < end + 300 and word.speaker]
        if not inside:
            continue
        best = max(set(inside), key=inside.count)
        if inside.count(best) / len(inside) < VOICE_MATCH_SHARE:
            continue
        if best in claimed:
            known.pop(best, None)
            continue
        claimed.add(best)
        known[best] = voice
    meeting_words = [
        SttWord(word.text, word.start_ms - offset_ms, word.end_ms - offset_ms, word.speaker, word.logprob)
        for word in words
        if word.start_ms >= offset_ms
    ]
    return meeting_words, known


def rows_from_scribe(
    result: SttResult, language: str | None, windows: list[tuple[KnownVoice, int, int]], offset_ms: int
) -> tuple[list[Row], dict[str, KnownVoice]]:
    """Turnos con persona a partir de las palabras de Scribe."""
    words, known = assign_known_voices(result.words, windows, offset_ms)
    return _clean_rows(group_words(words), language), known


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


async def _groq_rows(path: Path, api_key: str, language: str | None, vocabulary: list[str]) -> list[Row]:
    """Texto sin personas de la reunión entera, parte por parte.

    Si Groq se cae, la parte va a OpenAI (si hay key) en vez de perderse.
    """
    provider = get_stt_provider("groq", api_key)
    if get_settings().openai_api_key:
        provider = FallbackSttProvider([provider, get_stt_provider("openai", get_settings().openai_api_key)])
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


async def _known_voices(db, meeting: Meeting) -> list[KnownVoice]:
    """Personas del colegio que grabaron su voz y probablemente están en la reunión."""
    participants = (
        (await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id)))
        .scalars()
        .all()
    )
    wanted: list[uuid.UUID] = [meeting.created_by]
    wanted += [p.user_id for p in participants if p.user_id]
    names = {p.name.strip().lower() for p in participants if p.name}
    if names:
        members = (
            await db.execute(
                select(User.id, User.name)
                .join(OrganizationMember, OrganizationMember.user_id == User.id)
                .where(OrganizationMember.organization_id == meeting.organization_id)
            )
        ).all()
        wanted += [user_id for user_id, name in members if (name or "").strip().lower() in names]
    unique = list(dict.fromkeys(wanted))
    rows = (
        await db.execute(
            select(UserVoiceSample, User)
            .join(User, User.id == UserVoiceSample.user_id)
            .where(UserVoiceSample.user_id.in_(unique))
        )
    ).all()
    by_user = {user.id: (sample, user) for sample, user in rows}
    voices = []
    for user_id in unique:
        if user_id in by_user and len(voices) < MAX_KNOWN_VOICES:
            sample, user = by_user[user_id]
            voices.append(KnownVoice(f"voz_{len(voices) + 1}", user.id, user.name, sample.audio_wav))
    return voices


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
        decision = await plans.final_pass_for(db, meeting, total_ms / 1000)
        config = await resolve_stt(db, meeting.organization_id)
        vocabulary = await _vocabulary(db, meeting)
        known = await _known_voices(db, meeting) if decision.provider == "elevenlabs" else []
        language = meeting.language if meeting.language and meeting.language != "auto" else "es"
        organization_id, created_by = meeting.organization_id, meeting.created_by

    live = await _live_rows(meeting_id)
    # Lo dicho después del audio de trabajo (se grabó solo una parte con el
    # bridge, o se retomó otro día) no está en el audio: se conserva.
    after = [(hint, text, start, end) for start, end, text, hint in live if start >= total_ms]

    if decision.provider == "elevenlabs":
        people = await _people_pass(
            meeting_id, path, language, vocabulary, known, decision, organization_id, created_by, total_ms
        )
        if people is not None:
            rows, voices = people
            await _replace_transcript(meeting_id, rows + after, voices)
            return True

    # Sin personas (o ElevenLabs falló): texto de Groq, sin etiquetar a nadie.
    if any(hint in (MIC_SPEAKER, SYSTEM_SPEAKER) for _, _, _, hint in live):
        # Llamada de Meet/Zoom: el en vivo ya separó micrófono y sistema por
        # canal, y el audio de trabajo está mezclado. Se queda el en vivo.
        return False
    key = _groq_key(config)
    if not key:
        return False
    try:
        rows = await _groq_rows(path, key, language, vocabulary)
    except Exception as exc:  # noqa: BLE001 - queda el transcript en vivo
        log.warning("pasada final con Groq falló en %s: %s", meeting_id, exc)
        return False
    async with SessionLocal() as db:
        await plans.record_usage(
            db, kind="stt_final", provider="groq", model=GROQ_MODEL, unit="audio_seconds",
            quantity=total_ms / 1000, cost_usd=plans.stt_cost("groq", GROQ_MODEL, total_ms / 1000),
            organization_id=organization_id, user_id=created_by, meeting_id=meeting_id,
            meta={"reason": decision.reason},
        )
        await db.commit()
    if rows:
        await _replace_transcript(meeting_id, [(None, text, start, end) for _, text, start, end in rows] + after, {})
    return False


async def _people_pass(
    meeting_id: uuid.UUID,
    path: Path,
    language: str,
    vocabulary: list[str],
    known: list[KnownVoice],
    decision: "plans.FinalPass",
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    total_ms: int,
) -> tuple[list[Row], dict[str, KnownVoice]] | None:
    """Scribe sobre la reunión entera. None = falló y quedó pendiente de reintento."""
    prefix, windows = voice_prefix(known)
    offset_ms = len(prefix) // BYTES_PER_MS
    folder = recordings_dir()
    prefix_file = folder / f"{meeting_id}.voices.pcm"
    audio = people_path(meeting_id)
    try:
        sources = [path]
        if prefix:
            prefix_file.write_bytes(prefix)
            sources = [prefix_file, path]
        await _encode_mp3(sources, audio)
    except Exception as exc:  # noqa: BLE001 - sin mp3 no hay pasada con personas
        log.warning("no se pudo preparar el audio de %s para ElevenLabs: %s", meeting_id, exc)
        audio.unlink(missing_ok=True)
        return None
    finally:
        prefix_file.unlink(missing_ok=True)

    retry = {
        "offset_ms": offset_ms,
        "voices": [
            {"label": voice.label, "user_id": str(voice.user_id), "name": voice.name, "start_ms": start, "end_ms": end}
            for voice, start, end in windows
        ],
        "credits": decision.credits,
        "covered_by": decision.covered_by,
        "total_ms": total_ms,
        "attempts": 1,
    }
    try:
        result = await _scribe(audio, language, vocabulary)
    except Exception as exc:  # noqa: BLE001 - respaldo: Groq ahora, personas después
        log.warning("ElevenLabs falló en %s, queda pendiente: %s", meeting_id, exc)
        await _update_meta(meeting_id, people_status="pending", people_retry=retry)
        return None
    audio.unlink(missing_ok=True)
    rows, voices = rows_from_scribe(result, language, windows, offset_ms)
    await _charge(meeting_id, organization_id, created_by, retry, result)
    return rows, voices


async def _charge(
    meeting_id: uuid.UUID, organization_id: uuid.UUID, created_by: uuid.UUID, retry: dict, result: SttResult
) -> None:
    """Anota el consumo y los créditos (solo cuando la separación salió bien)."""
    seconds = (retry["total_ms"] + retry["offset_ms"]) / 1000
    async with SessionLocal() as db:
        await plans.record_usage(
            db, kind="stt_final", provider="elevenlabs", model=SCRIBE_MODEL, unit="audio_seconds",
            quantity=seconds, cost_usd=plans.stt_cost("elevenlabs", SCRIBE_MODEL, seconds, keyterms=True, entities=True),
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

    Si alguien ya corrigió el transcript a mano, no se pisa: se da por
    terminado sin personas.
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
                await _update_meta(meeting_id, people_status="failed", people_retry=None)
            else:
                await _update_meta(meeting_id, people_retry={**retry, "attempts": attempts})
            continue
        audio.unlink(missing_ok=True)
        windows = [
            (KnownVoice(v["label"], uuid.UUID(v["user_id"]), v["name"], b""), v["start_ms"], v["end_ms"])
            for v in retry.get("voices") or []
        ]
        rows, voices = rows_from_scribe(result, language, windows, int(retry.get("offset_ms") or 0))
        live = await _live_rows(meeting_id)
        after = [(hint, text, start, end) for start, end, text, hint in live if start >= int(retry.get("total_ms") or 0)]
        await _charge(meeting_id, organization_id, created_by, retry, result)
        await _replace_transcript(meeting_id, rows + [row for row in after if row[0] is None], voices)
        done += 1
    return done


async def retry_loop(interval_seconds: int = RETRY_EVERY_SECONDS) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            retried = await retry_pending_people()
            if retried:
                log.info("personas: %s reuniones separadas en un reintento", retried)
        except Exception:  # noqa: BLE001 - el reintento nunca tira abajo la API
            log.exception("personas: falló el reintento")


async def _replace_transcript(meeting_id: uuid.UUID, final: list[Row], known: dict[str, KnownVoice]) -> None:
    """Reemplaza el transcript en vivo por el final, con sus personas."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return
        await db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
        await db.execute(delete(Speaker).where(Speaker.meeting_id == meeting_id))

        speakers: dict[str, Speaker] = {}
        unnamed = 0
        for label, *_ in final:
            if label is None or label in speakers:
                continue
            voice = known.get(label)
            if voice is None:
                unnamed += 1
            speakers[label] = Speaker(
                meeting_id=meeting_id,
                label=(voice.name if voice else f"Persona {unnamed}")[:60],
                display_name=voice.name if voice else None,
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


# ── Nombres con la IA ────────────────────────────────────────────


def _mentioned(name: str, heard: set[str]) -> bool:
    """Alguna palabra del nombre (de 3+ letras) se dijo en la reunión."""
    return any(len(word) >= 3 and word in heard for word in _normalize(name).split())

NAMING_SYSTEM = """Identificás a las personas que hablan en la transcripción de una reunión de un colegio.
Usá solo lo que surge de la conversación y del contexto. Nunca inventes nombres: si nadie dice
cómo se llama una persona y no es inequívoco por el contexto, dejá "name" en null.
"role" es un rol corto en castellano (directora, docente, maestra de inglés, madre de Pedro,
padre, psicopedagoga, coordinadora...) o null si no se sabe."""


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
            context.append(f"La grabó: {creator.name} (personal del colegio)")
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
        for entry in entries:
            speaker = by_label.get(str(entry.get("label") or ""))
            if speaker is None or speaker.display_name:
                continue
            name = (entry.get("name") or "").strip() or None
            role = (entry.get("role") or "").strip() or None
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
                count += 1
            elif confidence >= 0.4:
                speaker.identity_suggestion = {"person_name": shown[:200], "confidence": round(confidence, 2), "source": "ia"}
        await db.commit()
    return count
