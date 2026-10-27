"""Pasada final por tramos de 5 minutos, hecha mientras la reunión sigue.

Antes la pasada final mandaba la reunión entera a ElevenLabs al tocar
"Finalizar": en una de una hora eran ~50 s de espera con la familia enfrente
(medición del 26/10, docs en la memoria del proyecto). Ahora:

- Mientras se graba, cada vez que se juntan 5 minutos nuevos de audio de
  trabajo, ese tramo (con 40 s del anterior, solapados) se transcribe y el
  resultado queda en disco (`<reunión>.chunks/<n>.json`). Ver `prepass_loop`.
- Al finalizar solo falta el último tramo. Los que no estén (una reunión
  importada, un tramo que falló, el servidor se reinició) se hacen ahí, de a
  varios a la vez.
- Las personas se unen entre tramos por el solapamiento: ElevenLabs numera a
  las personas de nuevo en cada tramo, pero en esos 40 s las mismas palabras
  aparecen en los dos tramos, al mismo tiempo, cada una con su etiqueta. Si
  "speaker_1" del tramo nuevo dice lo que "speaker_0" del anterior, es la
  misma persona. Quien no habla en el solapamiento queda como persona nueva
  (después la IA le pone nombre por la conversación).

Cuesta un ~13% más de audio a ElevenLabs (los solapamientos); no se le cobra
a la sede: se anota la duración real de la reunión. Si algo de esto falla,
quien llama vuelve a la pasada de siempre (la reunión entera de una vez).
"""
import asyncio
import json
import logging
import shutil
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .recording import pcm_path, recordings_dir
from .stt.base import SttEntity, SttResult, SttSegment, SttWord, pcm16_to_wav

log = logging.getLogger("echo.final_chunks")

CHUNK_MS = 5 * 60 * 1000
OVERLAP_MS = 40 * 1000
BYTES_PER_MS = 32  # PCM16 mono 16 kHz
SAMPLE_RATE = 16000
# Tramos en paralelo al finalizar (y entre todas las reuniones en el en vivo).
MAX_PARALLEL = 4
# Palabras iguales en los dos tramos a menos de esto se consideran la misma.
MATCH_MS = 600
MIN_VOTES = 3
CACHE_VERSION = 1

_semaphore = asyncio.Semaphore(MAX_PARALLEL)


def chunks_dir(meeting_id: uuid.UUID) -> Path:
    return recordings_dir() / f"{meeting_id}.chunks"


def bounds(index: int, total_ms: int) -> tuple[int, int]:
    """Dónde empieza y termina el tramo `index` (con el solapamiento al principio)."""
    start = max(0, index * CHUNK_MS - (OVERLAP_MS if index else 0))
    return start, min(total_ms, (index + 1) * CHUNK_MS)


def chunk_count(total_ms: int) -> int:
    return max(1, -(-total_ms // CHUNK_MS))


@dataclass
class Chunk:
    index: int
    start_ms: int
    end_ms: int
    provider: str  # elevenlabs | groq
    language: str | None
    words: list[SttWord]  # elevenlabs: palabra por palabra, con persona
    segments: list[SttSegment]  # groq: frases sin persona
    entities: list[SttEntity]


def _key(text: str) -> str:
    return "".join(char for char in text.lower() if char.isalnum())


def _load(path: Path) -> Chunk | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != CACHE_VERSION:
        return None
    return Chunk(
        index=data["index"], start_ms=data["start_ms"], end_ms=data["end_ms"], provider=data["provider"],
        language=data.get("language"),
        words=[SttWord(**word) for word in data.get("words") or []],
        segments=[SttSegment(**segment) for segment in data.get("segments") or []],
        entities=[SttEntity(**entity) for entity in data.get("entities") or []],
    )


def _save(meeting_id: uuid.UUID, chunk: Chunk) -> None:
    folder = chunks_dir(meeting_id)
    folder.mkdir(parents=True, exist_ok=True)
    data = {"version": CACHE_VERSION, **asdict(chunk)}
    temp = folder / f"{chunk.index}.json.tmp"
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(folder / f"{chunk.index}.json")


def cached(meeting_id: uuid.UUID, index: int, end_ms: int, provider: str, language: str | None) -> Chunk | None:
    chunk = _load(chunks_dir(meeting_id) / f"{index}.json")
    if chunk and chunk.end_ms == end_ms and chunk.provider == provider and chunk.language == language:
        return chunk
    return None


def discard(meeting_id: uuid.UUID) -> None:
    shutil.rmtree(chunks_dir(meeting_id), ignore_errors=True)


def _read_pcm(path: Path, start_ms: int, end_ms: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(start_ms * BYTES_PER_MS)
        return handle.read((end_ms - start_ms) * BYTES_PER_MS)


async def _mp3(pcm: bytes) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
        "-codec:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate(pcm)
    if process.returncode != 0 or not out:
        raise RuntimeError((err or b"").decode(errors="ignore")[-300:] or "ffmpeg falló")
    return out


async def transcribe(
    meeting_id: uuid.UUID,
    path: Path,
    index: int,
    total_ms: int,
    provider: str,
    engine,
    language: str | None,
    vocabulary: list[str],
) -> Chunk:
    """Transcribe un tramo y lo guarda. `engine`: el proveedor de STT ya armado."""
    start, end = bounds(index, total_ms)
    async with _semaphore:
        pcm = _read_pcm(path, start, end)
        began = time.monotonic()
        if provider == "elevenlabs":
            result: SttResult = await engine.transcribe_file(await _mp3(pcm), f"tramo-{index}.mp3", language, vocabulary)
        else:
            result = await engine.transcribe_file(pcm16_to_wav(pcm, SAMPLE_RATE), f"tramo-{index}.wav", language, vocabulary)
        log.info("tramo %s/%s de %s: %.1f s", index, chunk_count(total_ms), meeting_id, time.monotonic() - began)
    chunk = Chunk(
        index=index, start_ms=start, end_ms=end, provider=provider, language=language,
        words=[replace(word, start_ms=word.start_ms + start, end_ms=word.end_ms + start) for word in result.words],
        segments=[
            replace(segment, start_ms=segment.start_ms + start, end_ms=min(segment.end_ms + start, end))
            for segment in result.segments
        ] if provider != "elevenlabs" else [],
        entities=list(result.entities),
    )
    _save(meeting_id, chunk)
    return chunk


async def all_chunks(
    meeting_id: uuid.UUID, path: Path, total_ms: int, provider: str, engine, language: str | None, vocabulary: list[str]
) -> list[Chunk]:
    """Todos los tramos de la reunión: los guardados en el en vivo y el resto, ahora en paralelo."""
    chunks: dict[int, Chunk] = {}
    missing = []
    for index in range(chunk_count(total_ms)):
        _, end = bounds(index, total_ms)
        hit = cached(meeting_id, index, end, provider, language)
        if hit:
            chunks[index] = hit
        else:
            missing.append(index)
    log.info("pasada por tramos de %s: %d listos, %d por hacer", meeting_id, len(chunks), len(missing))
    results = await asyncio.gather(
        *(transcribe(meeting_id, path, index, total_ms, provider, engine, language, vocabulary) for index in missing)
    )
    for chunk in results:
        chunks[chunk.index] = chunk
    return [chunks[index] for index in sorted(chunks)]


# ── Unir los tramos ──────────────────────────────────────────────


def _speaker_map(previous: list[SttWord], current: list[SttWord], start: int, end: int) -> dict[str, str]:
    """Etiqueta del tramo nuevo → etiqueta global, por las palabras del solapamiento."""
    before: dict[str, list[SttWord]] = {}
    for word in previous:
        if start <= word.start_ms < end and word.speaker:
            before.setdefault(_key(word.text), []).append(word)
    votes: dict[str, Counter] = {}
    for word in current:
        if not (start <= word.start_ms < end) or not word.speaker:
            continue
        candidates = [w for w in before.get(_key(word.text), []) if abs(w.start_ms - word.start_ms) <= MATCH_MS]
        if not candidates or not _key(word.text):
            continue
        twin = min(candidates, key=lambda w: abs(w.start_ms - word.start_ms))
        votes.setdefault(word.speaker, Counter())[twin.speaker] += 1
    mapping = {}
    for raw, counter in votes.items():
        best, count = counter.most_common(1)[0]
        if count >= MIN_VOTES and count >= 0.6 * sum(counter.values()):
            mapping[raw] = best
    return mapping


def stitch_words(chunks: list[Chunk]) -> list[SttWord]:
    """Las palabras de toda la reunión, con una sola numeración de personas."""
    words: list[SttWord] = []
    previous: list[SttWord] = []
    next_id = 0
    for position, chunk in enumerate(chunks):
        mapping: dict[str, str] = {}
        if position:
            prior = chunks[position - 1]
            mapping = _speaker_map(previous, chunk.words, chunk.start_ms, prior.end_ms)
        for word in chunk.words:
            if word.speaker and word.speaker not in mapping:
                mapping[word.speaker] = f"speaker_{next_id}"
                next_id += 1
        relabeled = [replace(word, speaker=mapping.get(word.speaker) if word.speaker else None) for word in chunk.words]
        if position:
            # Del solapamiento, la primera mitad del tramo anterior y la segunda del nuevo.
            cut = (chunk.start_ms + chunks[position - 1].end_ms) // 2
            words = [w for w in words if w.start_ms < cut] + [w for w in relabeled if w.start_ms >= cut]
        else:
            words = relabeled
        previous = relabeled
    return words


def stitch_segments(chunks: list[Chunk]) -> list[SttSegment]:
    """Las frases de toda la reunión (sin personas), sin repetir el solapamiento."""
    segments: list[SttSegment] = []
    for position, chunk in enumerate(chunks):
        if position:
            cut = (chunk.start_ms + chunks[position - 1].end_ms) // 2
            segments = [s for s in segments if s.start_ms < cut] + [s for s in chunk.segments if s.start_ms >= cut]
        else:
            segments = list(chunk.segments)
    return segments


def entities(chunks: list[Chunk]) -> list[SttEntity]:
    seen, out = set(), []
    for chunk in chunks:
        for entity in chunk.entities:
            key = (entity.text, entity.entity_type)
            if key not in seen:
                seen.add(key)
                out.append(entity)
    return out


# ── Mientras se graba ────────────────────────────────────────────

PREPASS_EVERY_SECONDS = 20


async def _prepass_once() -> None:
    """Para cada reunión que se está grabando, transcribe los tramos completos que falten."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from ..config import get_settings
    from ..db import SessionLocal
    from ..models import Meeting
    from . import plans
    from .ai_settings import resolve_stt
    from .diarization import _groq_key, _vocabulary
    from .stt.base import get_stt_provider
    from .stt.channels import stt_language

    async with SessionLocal() as db:
        meetings = (
            await db.execute(
                select(Meeting).where(
                    Meeting.status.in_(("live", "paused")),
                    Meeting.deleted_at.is_(None),
                    Meeting.updated_at > datetime.now(UTC) - timedelta(hours=3),
                )
            )
        ).scalars().all()
        jobs = []
        for meeting in meetings:
            path = pcm_path(meeting.id)
            if not path.exists() or (meeting.meta or {}).get("audio_limit"):
                continue
            recorded_ms = path.stat().st_size // BYTES_PER_MS
            complete = recorded_ms // CHUNK_MS  # tramos con sus 5 minutos enteros
            if not complete:
                continue
            decision = await plans.final_pass_for(db, meeting, recorded_ms / 1000)
            # Solo lo que ya está cubierto (plan de la sede o personal): lo que
            # se paga con créditos se decide y se reserva al finalizar.
            if decision.provider == "elevenlabs" and decision.credits:
                continue
            language = stt_language(meeting.language)
            if decision.provider == "elevenlabs":
                engine = get_stt_provider("elevenlabs", get_settings().elevenlabs_api_key)
            else:
                groq = _groq_key(await resolve_stt(db, meeting.organization_id))
                if not groq:
                    continue
                engine = get_stt_provider("groq", groq)
            for index in range(complete):
                _, end = bounds(index, (index + 1) * CHUNK_MS)
                if not cached(meeting.id, index, end, decision.provider, language):
                    jobs.append((meeting.id, path, index, decision.provider, engine, language, await _vocabulary(db, meeting)))
                    break  # de a un tramo por reunión por vuelta
    for meeting_id, path, index, provider, engine, language, vocabulary in jobs:
        try:
            await transcribe(meeting_id, path, index, (index + 1) * CHUNK_MS, provider, engine, language, vocabulary)
        except Exception as exc:  # noqa: BLE001 - se reintenta en la próxima vuelta o al finalizar
            log.warning("tramo %s de %s falló: %s", index, meeting_id, exc)


async def prepass_loop() -> None:
    while True:
        try:
            await _prepass_once()
        except Exception:  # noqa: BLE001 - el loop nunca se cae
            log.exception("pasada por tramos: vuelta fallida")
        await asyncio.sleep(PREPASS_EVERY_SECONDS)
