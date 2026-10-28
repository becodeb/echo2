"""Pasada final por tramos de ~5 minutos, hecha mientras la reunión sigue.

Antes la pasada final mandaba la reunión entera a ElevenLabs al tocar
"Finalizar": en una de una hora eran ~50 s de espera con la familia enfrente
(medición del 26/10, docs en la memoria del proyecto). Ahora:

- Mientras se graba, cada vez que se juntan ~5 minutos nuevos de audio de
  trabajo, ese tramo se transcribe y el resultado queda en disco
  (`<reunión>.chunks/<n>.json`). Ver `prepass_loop`.
- Al finalizar solo falta el último tramo. Los que no estén (una reunión
  importada, un tramo que falló, el servidor se reinició) se hacen ahí, de a
  varios a la vez.
- Cada tramo se corta en el momento más callado de los últimos 30 s antes de
  los 5 minutos, así no se parte ninguna palabra y no hace falta repetir audio:
  ElevenLabs cobra exactamente lo que duró la reunión.
- ElevenLabs numera a las personas de nuevo en cada tramo. Quién es quién se
  sabe por la voz: de cada persona de cada tramo se saca una huella (hasta
  15 s de sus turnos limpios, en la CPU de Echo, sin terceros) y se compara
  con todas las personas que ya aparecieron en la reunión. Ver `link_voices`.

Hasta el 28/10 las personas se unían por las palabras de 40 s repetidos entre
tramos: quien no hablaba justo ahí quedaba como persona nueva para siempre, y
una reunión de 2 horas con 4 participantes salió con 21 personas. Ese método
queda solo de respaldo, si el modelo de voz no está (`mode == "overlap"`).

Si algo de esto falla, quien llama vuelve a la pasada de siempre (la reunión
entera de una vez).
"""
import asyncio
import json
import logging
import shutil
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from . import voiceprint
from .recording import pcm_path, recordings_dir
from .stt.base import SttEntity, SttResult, SttSegment, SttWord, pcm16_to_wav
from .stt.elevenlabs import group_words

log = logging.getLogger("echo.final_chunks")

CHUNK_MS = 5 * 60 * 1000
# El corte se busca en los últimos 30 s antes de los 5 minutos: el momento
# más callado (400 ms de menor energía), para no partir una palabra.
CUT_SEARCH_MS = 30 * 1000
QUIET_WINDOW_MS = 400
# Al finalizar, un resto de hasta 1 minuto más va con el último tramo en vez
# de quedar como un tramo de segundos (personas con una sola frase).
TAIL_SLACK_MS = 60 * 1000
# Solo en el modo de respaldo (sin modelo de voz): tramos fijos de 5 minutos
# con 40 s del anterior, para unir a las personas por las palabras.
OVERLAP_MS = 40 * 1000
BYTES_PER_MS = 32  # PCM16 mono 16 kHz
SAMPLE_RATE = 16000
# Tramos en paralelo al finalizar (y entre todas las reuniones en el en vivo).
MAX_PARALLEL = 4
# Palabras iguales en los dos tramos a menos de esto se consideran la misma.
MATCH_MS = 600
MIN_VOTES = 3
CACHE_VERSION = 2

# ── Unir por la voz ──────────────────────────────────────────────
# Cuánto de cada persona en cada tramo: más no mejora y cuesta CPU (~40 ms
# por segundo de audio; el servidor tiene 2 vCPU).
VOICE_MS = 15000
# El tramo que se hace al tocar "Finalizar" está en la espera: ahí, 8 s.
VOICE_MS_FINAL = 8000
# Menos que esto y no se saca huella: ni siquiera para las frases cortas.
VOICE_MIN_MS = 1500
# Las huellas se comparan "centradas": se les resta el promedio de todas las
# de la reunión. Crudas, en las grabaciones de Northfield del 26/10 dos personas
# distintas daban 0,89 de mediana (la sala y el celular pesan más que la voz);
# centradas, la misma persona da 0,46 de mediana y otra −0,26
# (bench/stitch_sim.py, 28/10).
# Una persona del tramo es alguien nuevo si se parece así de poco al resto de
# la persona que le tocó (centradas; crudas si hay menos de 3 huellas). Con 0
# a veces sobra una persona; más bajo, alguien que llega cuando otro dejó de
# hablar queda mezclado con él, que es peor (bench/stitch_sim.py, 28/10).
NEW_CENTERED = 0.0
NEW_RAW = 0.50
# Al final, dos personas que nunca coincidieron en un tramo y se parecen así
# (centradas) son la misma: por ejemplo, ElevenLabs partió a alguien en dos
# dentro de un tramo y eso sumó una persona de más.
MERGE_CENTERED = 0.50
ITERATIONS = 20

_semaphore = asyncio.Semaphore(MAX_PARALLEL)
_voice_semaphore = asyncio.Semaphore(1)


def chunks_dir(meeting_id: uuid.UUID) -> Path:
    return recordings_dir() / f"{meeting_id}.chunks"


# ── Dónde se corta ───────────────────────────────────────────────


def _read_pcm(path: Path, start_ms: int, end_ms: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(start_ms * BYTES_PER_MS)
        return handle.read((end_ms - start_ms) * BYTES_PER_MS)


def quiet_point(pcm: bytes, offset_ms: int) -> int:
    """El centro de los 400 ms más callados de `pcm` (que empieza en `offset_ms`)."""
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    frame = SAMPLE_RATE // 50  # 20 ms
    frames = len(samples) // frame
    width = QUIET_WINDOW_MS // 20
    if frames <= width:
        return offset_ms + len(samples) * 1000 // SAMPLE_RATE
    energy = (samples[: frames * frame].reshape(frames, frame) ** 2).mean(axis=1)
    windows = np.convolve(energy, np.ones(width), mode="valid")
    # Entre momentos igual de callados, el más cercano a los 5 minutos.
    best = int(len(windows) - 1 - np.argmin(windows[::-1]))
    return offset_ms + (best + width // 2) * 20


def _plan_path(meeting_id: uuid.UUID) -> Path:
    return chunks_dir(meeting_id) / "plan.json"


def load_plan(meeting_id: uuid.UUID) -> dict:
    """{"mode": "voice" | "overlap", "cuts": [ms...]}: dónde termina cada tramo."""
    try:
        plan = json.loads(_plan_path(meeting_id).read_text(encoding="utf-8"))
        if plan.get("version") == CACHE_VERSION:
            return plan
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "mode": "voice" if voiceprint.available() else "overlap", "cuts": []}


def _save_plan(meeting_id: uuid.UUID, plan: dict) -> None:
    folder = chunks_dir(meeting_id)
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / "plan.json.tmp"
    temp.write_text(json.dumps(plan), encoding="utf-8")
    temp.replace(_plan_path(meeting_id))


def extend_plan(meeting_id: uuid.UUID, path: Path, recorded_ms: int, final: bool) -> dict:
    """Agrega los cortes que ya se pueden decidir con `recorded_ms` de audio.

    Mientras se graba, un corte apenas hay 5 minutos nuevos. Al finalizar, el
    resto se corta igual pero el último tramo puede tener hasta 6 minutos.
    """
    plan = load_plan(meeting_id)
    cuts: list[int] = plan["cuts"]
    changed = False
    while True:
        start = cuts[-1] if cuts else 0
        remaining = recorded_ms - start
        if remaining < CHUNK_MS or (final and remaining <= CHUNK_MS + TAIL_SLACK_MS):
            break
        target = start + CHUNK_MS
        if plan["mode"] == "overlap":
            cut = target
        else:
            search = target - CUT_SEARCH_MS
            cut = quiet_point(_read_pcm(path, search, target), search)
        cuts.append(cut)
        changed = True
    if changed:
        _save_plan(meeting_id, plan)
    return plan


def spans(plan: dict, total_ms: int) -> list[tuple[int, int]]:
    """(inicio, fin) de cada tramo. En el respaldo, con 40 s del anterior."""
    ends = [cut for cut in plan["cuts"] if cut < total_ms] + [total_ms]
    out = []
    for index, end in enumerate(ends):
        start = ends[index - 1] if index else 0
        if plan["mode"] == "overlap" and index:
            start = max(0, start - OVERLAP_MS)
        out.append((start, end))
    return out


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
    # Etiqueta de ElevenLabs en este tramo → {"vector": huella, "ms": audio usado}.
    voices: dict[str, dict] = field(default_factory=dict)


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
        voices=data.get("voices") or {},
    )


def _save(meeting_id: uuid.UUID, chunk: Chunk) -> None:
    folder = chunks_dir(meeting_id)
    folder.mkdir(parents=True, exist_ok=True)
    data = {"version": CACHE_VERSION, **asdict(chunk)}
    temp = folder / f"{chunk.index}.json.tmp"
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temp.replace(folder / f"{chunk.index}.json")


def cached(
    meeting_id: uuid.UUID, index: int, start_ms: int, end_ms: int, provider: str, language: str | None
) -> Chunk | None:
    chunk = _load(chunks_dir(meeting_id) / f"{index}.json")
    if (
        chunk
        and chunk.start_ms == start_ms
        and chunk.end_ms == end_ms
        and chunk.provider == provider
        and chunk.language == language
    ):
        return chunk
    return None


def discard(meeting_id: uuid.UUID) -> None:
    shutil.rmtree(chunks_dir(meeting_id), ignore_errors=True)


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


# ── La huella de cada persona del tramo ──────────────────────────


def chunk_voices(pcm: bytes, words: list[SttWord], limit_ms: int = VOICE_MS) -> dict[str, dict]:
    """Una huella por persona del tramo, con sus turnos limpios más largos.

    `words` con tiempos relativos al tramo. Turnos de al menos 1 s que no se
    pisan con otra persona; los más largos primero (menos ruido de cambios de
    turno), hasta `limit_ms`. Una sola huella por persona por tramo.
    """
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
    turns = [(segment.speaker, segment.start_ms, segment.end_ms) for segment in group_words(words)]
    clean = voiceprint.clean_turns(turns)
    voices: dict[str, dict] = {}
    for who in dict.fromkeys(w for w, _, _ in clean):
        mine = sorted(((s, e) for w, s, e in clean if w == who), key=lambda span: span[0] - span[1])
        pieces, taken = [], 0
        for start, end in mine:
            if taken >= limit_ms:
                break
            end = min(end, start + limit_ms - taken)
            piece = samples[start * SAMPLE_RATE // 1000:end * SAMPLE_RATE // 1000]
            if len(piece):
                pieces.append(piece)
                taken += end - start
        if taken < VOICE_MIN_MS:
            continue
        vector = voiceprint.embed(np.concatenate(pieces))
        if vector is not None:
            voices[who] = {"vector": [round(float(x), 5) for x in vector], "ms": taken}
    return voices


async def transcribe(
    meeting_id: uuid.UUID,
    path: Path,
    index: int,
    span: tuple[int, int],
    provider: str,
    engine,
    language: str | None,
    vocabulary: list[str],
    with_voices: bool = False,
    voice_ms: int = VOICE_MS,
) -> Chunk:
    """Transcribe un tramo y lo guarda. `engine`: el proveedor de STT ya armado."""
    start, end = span
    async with _semaphore:
        pcm = _read_pcm(path, start, end)
        began = time.monotonic()
        if provider == "elevenlabs":
            result: SttResult = await engine.transcribe_file(await _mp3(pcm), f"tramo-{index}.mp3", language, vocabulary)
        else:
            result = await engine.transcribe_file(pcm16_to_wav(pcm, SAMPLE_RATE), f"tramo-{index}.wav", language, vocabulary)
        log.info("tramo %s de %s (%d-%d s): %.1f s", index, meeting_id, start // 1000, end // 1000, time.monotonic() - began)
    voices: dict[str, dict] = {}
    if with_voices and provider == "elevenlabs" and result.words:
        began = time.monotonic()
        async with _voice_semaphore:  # de a una: el extractor usa un solo hilo y el servidor tiene 2
            voices = await asyncio.to_thread(chunk_voices, pcm, result.words, voice_ms)
        log.info("huellas del tramo %s de %s: %d en %.1f s", index, meeting_id, len(voices), time.monotonic() - began)
    chunk = Chunk(
        index=index, start_ms=start, end_ms=end, provider=provider, language=language,
        words=[replace(word, start_ms=word.start_ms + start, end_ms=word.end_ms + start) for word in result.words],
        segments=[
            replace(segment, start_ms=segment.start_ms + start, end_ms=min(segment.end_ms + start, end))
            for segment in result.segments
        ] if provider != "elevenlabs" else [],
        entities=list(result.entities),
        voices=voices,
    )
    _save(meeting_id, chunk)
    return chunk


async def all_chunks(
    meeting_id: uuid.UUID, path: Path, total_ms: int, provider: str, engine, language: str | None, vocabulary: list[str]
) -> tuple[list[Chunk], str]:
    """Todos los tramos de la reunión (los guardados en el en vivo y el resto, ahora en paralelo) y el modo."""
    plan = extend_plan(meeting_id, path, total_ms, final=True)
    with_voices = plan["mode"] == "voice"
    chunks: dict[int, Chunk] = {}
    missing = []
    for index, span in enumerate(spans(plan, total_ms)):
        hit = cached(meeting_id, index, *span, provider, language)
        if hit and (hit.voices or not with_voices or provider != "elevenlabs" or not hit.words):
            chunks[index] = hit
        else:
            missing.append((index, span))
    log.info("pasada por tramos de %s: %d listos, %d por hacer", meeting_id, len(chunks), len(missing))
    results = await asyncio.gather(
        *(
            transcribe(meeting_id, path, index, span, provider, engine, language, vocabulary, with_voices, VOICE_MS_FINAL)
            for index, span in missing
        )
    )
    for chunk in results:
        chunks[chunk.index] = chunk
    return [chunks[index] for index in sorted(chunks)], plan["mode"]


# ── Unir los tramos por la voz ───────────────────────────────────


def _order(words: list[SttWord]) -> list[str]:
    return list(dict.fromkeys(word.speaker for word in words if word.speaker))


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / (np.linalg.norm(vectors, axis=-1, keepdims=True) + 1e-9)


def link_voices(chunks: list[Chunk]) -> tuple[list[dict[str, str]], dict[str, np.ndarray]]:
    """Etiqueta de cada tramo → persona de la reunión, y la huella de cada persona.

    ElevenLabs ya separó bien a las personas dentro de cada tramo; lo que falta
    es saber cuál es cuál entre tramos. Por eso cada tramo se asigna entero,
    como una permutación: sus personas van a las de la reunión con la
    combinación que más se parece en conjunto (algoritmo húngaro), y nunca dos
    del mismo tramo a la misma. Las personas de la reunión son tantas como el
    máximo que ElevenLabs separó a la vez en un tramo; se arranca por ese tramo
    y se repite asignar / recalcular hasta que no cambia. Comparar el tramo
    completo resuelve dos voces parecidas que, de a una, se confunden (27/10:
    la docente y la mamá).

    Alguien que no se parece a nadie es una persona nueva. Al final, dos
    personas que nunca coincidieron en un tramo y tienen la misma voz se juntan.
    """
    labels_of = [_order(chunk.words) for chunk in chunks]
    nodes = [
        (position, label, np.asarray(chunk.voices[label]["vector"], dtype=np.float64), float(chunk.voices[label]["ms"]))
        for position, chunk in enumerate(chunks)
        for label in labels_of[position]
        if label in chunk.voices
    ]
    raw = _unit(np.array([vector for _, _, vector, _ in nodes])) if nodes else np.zeros((0, voiceprint.DIM))
    centered = len(nodes) >= 3
    vectors = _unit(raw - raw.mean(axis=0)) if centered else raw
    weights = np.array([ms for *_, ms in nodes])
    new_below = NEW_CENTERED if centered else NEW_RAW

    by_chunk: dict[int, list[int]] = {}
    for index, (position, *_) in enumerate(nodes):
        by_chunk.setdefault(position, []).append(index)
    person_of: dict[int, int] = {}
    if nodes:
        size = max(len(members) for members in by_chunk.values())
        seed = max((c for c, m in by_chunk.items() if len(m) == size), key=lambda c: weights[by_chunk[c]].sum())
        centroids = vectors[by_chunk[seed]].copy()
        for _ in range(ITERATIONS):
            assigned: dict[int, int] = {}
            for members in by_chunk.values():
                cost = [[-float(vectors[i] @ centroid) for centroid in centroids] for i in members]
                for i, person in zip(members, voiceprint._hungarian(cost), strict=True):
                    assigned[i] = person
            if assigned == person_of:
                break
            person_of = assigned
            for person in range(len(centroids)):
                members = [i for i, p in person_of.items() if p == person]
                if members:
                    centroids[person] = _unit((vectors[members] * weights[members, None]).sum(axis=0))
        # Quien no se parece al resto de la persona que le tocó (comparado sin
        # contarse a sí mismo) es alguien nuevo: por ejemplo, la directora que
        # llega cuando el papá ya no habla ocuparía el lugar del papá.
        flagged = []
        for i, person in person_of.items():
            others = [j for j, q in person_of.items() if q == person and j != i]
            if others:
                rest = _unit((vectors[others] * weights[others, None]).sum(axis=0))
                if float(vectors[i] @ rest) < new_below:
                    flagged.append(i)
        for i in flagged:
            person_of[i] = len(centroids)
            centroids = np.vstack([centroids, vectors[i]])

        # Juntar a quienes nunca coincidieron en un tramo y tienen la misma voz.
        while True:
            groups = {p: [i for i, q in person_of.items() if q == p] for p in set(person_of.values())}
            seen = {p: {nodes[i][0] for i in members} for p, members in groups.items()}
            best = None
            for a, b in ((a, b) for a in groups for b in groups if a < b and not (seen[a] & seen[b])):
                ca = _unit((vectors[groups[a]] * weights[groups[a], None]).sum(axis=0))
                cb = _unit((vectors[groups[b]] * weights[groups[b], None]).sum(axis=0))
                score = float(ca @ cb)
                if centered and score >= MERGE_CENTERED and (best is None or score > best[0]):
                    best = (score, a, b)
            if best is None:
                break
            for i, p in person_of.items():
                if p == best[2]:
                    person_of[i] = best[1]

    mappings: list[dict[str, str]] = [{} for _ in chunks]
    for i, person in person_of.items():
        position, label, *_ = nodes[i]
        mappings[position][label] = f"p{person}"
    # Sin ni 1,5 s limpios en un tramo (una frase suelta, o siempre pisado):
    # persona aparte. No se adivina con quién va.
    extra = 0
    for position, labels in enumerate(labels_of):
        for label in labels:
            if label not in mappings[position]:
                mappings[position][label] = f"x{extra}"
                extra += 1
    # Numeración final en orden de aparición: speaker_0, speaker_1...
    order: dict[str, str] = {}
    for position, labels in enumerate(labels_of):
        for label in labels:
            person = mappings[position][label]
            if person not in order:
                order[person] = f"speaker_{len(order)}"
    final = [{label: order[person] for label, person in mapping.items()} for mapping in mappings]
    # La huella de cada persona para "Mi voz": cruda (sin centrar), como las muestras.
    prints: dict[str, np.ndarray] = {}
    for person in set(person_of.values()):
        members = [i for i, p in person_of.items() if p == person]
        prints[order[f"p{person}"]] = _unit((raw[members] * weights[members, None]).sum(axis=0)).astype(np.float32)
    return final, prints


def _speaker_map(previous: list[SttWord], current: list[SttWord], start: int, end: int) -> dict[str, str]:
    """Respaldo: etiqueta del tramo nuevo → etiqueta global, por las palabras del solapamiento."""
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


def _overlap_mappings(chunks: list[Chunk]) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    previous: list[SttWord] = []
    next_id = 0
    for position, chunk in enumerate(chunks):
        mapping: dict[str, str] = {}
        if position:
            mapping = _speaker_map(previous, chunk.words, chunk.start_ms, chunks[position - 1].end_ms)
        for word in chunk.words:
            if word.speaker and word.speaker not in mapping:
                mapping[word.speaker] = f"speaker_{next_id}"
                next_id += 1
        previous = [replace(word, speaker=mapping.get(word.speaker) if word.speaker else None) for word in chunk.words]
        mappings.append(mapping)
    return mappings


def stitch_words(chunks: list[Chunk], mode: str = "voice") -> tuple[list[SttWord], dict[str, np.ndarray]]:
    """Las palabras de toda la reunión, con una sola numeración de personas, y la huella de cada una.

    Las huellas (solo en el modo por voz) las usa "Mi voz" para sugerir
    nombres sin volver a calcularlas al finalizar.
    """
    prints: dict[str, np.ndarray] = {}
    if mode == "voice":
        mappings, prints = link_voices(chunks)
    else:
        mappings = _overlap_mappings(chunks)
    words: list[SttWord] = []
    for position, (chunk, mapping) in enumerate(zip(chunks, mappings, strict=True)):
        relabeled = [replace(word, speaker=mapping.get(word.speaker) if word.speaker else None) for word in chunk.words]
        if position:
            # Del solapamiento (si hay), la primera mitad del tramo anterior y la segunda del nuevo.
            cut = (chunk.start_ms + chunks[position - 1].end_ms) // 2
            words = [w for w in words if w.start_ms < cut] + [w for w in relabeled if w.start_ms >= cut]
        else:
            words = relabeled
    return words, prints


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
            if recorded_ms < CHUNK_MS:
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
            plan = extend_plan(meeting.id, path, recorded_ms, final=False)
            with_voices = plan["mode"] == "voice"
            # Solo los tramos con su corte decidido (el último, el que se está grabando, no).
            for index, span in enumerate(spans(plan, recorded_ms)[: len(plan["cuts"])]):
                if not cached(meeting.id, index, *span, decision.provider, language):
                    jobs.append((
                        meeting.id, path, index, span, decision.provider, engine, language,
                        await _vocabulary(db, meeting), with_voices,
                    ))
                    break  # de a un tramo por reunión por vuelta
    for meeting_id, path, index, span, provider, engine, language, vocabulary, with_voices in jobs:
        try:
            await transcribe(meeting_id, path, index, span, provider, engine, language, vocabulary, with_voices)
        except Exception as exc:  # noqa: BLE001 - se reintenta en la próxima vuelta o al finalizar
            log.warning("tramo %s de %s falló: %s", index, meeting_id, exc)


async def prepass_loop() -> None:
    while True:
        try:
            await _prepass_once()
        except Exception:  # noqa: BLE001 - el loop nunca se cae
            log.exception("pasada por tramos: vuelta fallida")
        await asyncio.sleep(PREPASS_EVERY_SECONDS)
