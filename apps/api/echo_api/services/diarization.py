"""Quién habló: separación de hablantes escuchando la reunión entera.

En vivo el audio va en tramos cortos, y un modelo que separa voces numera a
las personas dentro de cada tramo: la "A" de un tramo puede ser la "B" del
siguiente. Por eso la separación se hace al finalizar, sobre el audio de
trabajo de la reunión (services/recording.py):

1. El audio se manda a gpt-4o-transcribe-diarize en partes de 10 minutos. A
   partir de la segunda parte se le pasan muestras de voz de las personas ya
   encontradas ("persona_1", "persona_2"...), así sigue llamándolas igual.
2. Las personas del colegio que grabaron su voz en Ajustes → Mi voz van como
   voces conocidas desde el principio: salen con su nombre.
3. Las voces se asignan al transcript que ya existe (el de gpt-4o-transcribe,
   que escribe mejor y respeta el diccionario) por coincidencia de tiempos. Si
   un tramo tiene dos personas, se parte por oraciones.
4. `name_speakers` le pide a la IA que deduzca de la conversación quién es
   cada persona sin nombre ("Mamá de Pedro"). Si no está segura, queda como
   sugerencia que la persona confirma en el transcript.

Solo con OpenAI (es el único proveedor configurado que separa hablantes). Si
algo falla, el pipeline sigue con la consolidación de siempre.
"""
import base64
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

import httpx
from sqlalchemy import delete, select, update

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
from .ai_settings import resolve_stt
from .recording import pcm_path
from .stt.base import OPENAI_FILE_MODEL, pcm16_to_wav

log = logging.getLogger("echo.diarization")

TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
BYTES_PER_MS = 32  # PCM16 mono 16 kHz
PART_MS = 10 * 60 * 1000  # 10 min de WAV ≈ 19 MB, bajo el límite de 25 MB
MIN_AUDIO_MS = 5000
MIN_PART_MS = 3000
MAX_REFERENCES = 4  # lo que acepta la API
REF_MIN_MS = 2000
REF_MAX_MS = 8000
# Si una voz ocupa al menos esto del tramo, el tramo es de esa persona.
DOMINANT_SHARE = 0.65
SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]


@dataclass
class DiarSegment:
    start_ms: int
    end_ms: int
    label: str
    text: str


@dataclass
class KnownVoice:
    label: str
    user_id: uuid.UUID
    name: str
    wav: bytes


# ── Asignación (pura, sin base ni red) ───────────────────────────


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text or "") if part.strip()]
    return parts or [text]


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\wáéíóúüñ ]", " ", (text or "").lower()).split())


def _coverage(sentence: str, candidate: str) -> float:
    """Cuánto de la oración aparece en el texto del segmento con voz."""
    a, b = _normalize(sentence), _normalize(candidate)
    if not a or not b:
        return 0.0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(a)


def assign_speakers(
    transcript: list[tuple[int, int, str]], diarized: list[DiarSegment]
) -> list[list[tuple[str | None, str, int, int]]]:
    """Para cada tramo del transcript, en qué partes (hablante, texto, inicio, fin) queda."""
    out: list[list[tuple[str | None, str, int, int]]] = []
    for start, end, text in transcript:
        end = max(end, start + 1)
        overlaps: dict[str, int] = defaultdict(int)
        nearby: list[DiarSegment] = []
        for seg in diarized:
            overlap = min(end, seg.end_ms) - max(start, seg.start_ms)
            if overlap > 0:
                overlaps[seg.label] += overlap
            if seg.end_ms >= start - 1000 and seg.start_ms <= end + 1000:
                nearby.append(seg)

        if not overlaps:
            nearest = min(
                diarized,
                key=lambda seg: max(seg.start_ms - end, start - seg.end_ms, 0),
                default=None,
            )
            gap = max(nearest.start_ms - end, start - nearest.end_ms, 0) if nearest else None
            label = nearest.label if nearest is not None and gap <= 2000 else None
            out.append([(label, text, start, end)])
            continue

        best = max(overlaps, key=overlaps.get)
        sentences = _sentences(text)
        if overlaps[best] / sum(overlaps.values()) >= DOMINANT_SHARE or len(overlaps) < 2 or len(sentences) < 2:
            out.append([(best, text, start, end)])
            continue

        # Dos o más personas en el mismo tramo: cada oración va con el segmento
        # de voz que mejor la contiene.
        groups: list[list] = []
        for sentence in sentences:
            match = max(nearby, key=lambda seg: _coverage(sentence, seg.text))
            label = match.label if _coverage(sentence, match.text) >= 0.3 else (groups[-1][0] if groups else best)
            when = min(max(match.start_ms, start), end)
            if groups and groups[-1][0] == label:
                groups[-1][1] += " " + sentence
            else:
                groups.append([label, sentence, when])
        pieces = []
        for index, (label, piece_text, when) in enumerate(groups):
            piece_start = start if index == 0 else max(when, pieces[-1][2] + 1)
            pieces.append([label, piece_text, piece_start, end])
            if index > 0:
                pieces[-2][3] = piece_start
        out.append([tuple(piece) for piece in pieces])
    return out


# ── Llamada a la API ─────────────────────────────────────────────


async def _diarize_part(api_key: str, wav: bytes, references: list[tuple[str, bytes]]) -> list[dict]:
    form: dict = {"model": OPENAI_FILE_MODEL, "response_format": "diarized_json", "chunking_strategy": "auto"}
    if references:
        form["known_speaker_names[]"] = [name for name, _ in references]
        form["known_speaker_references[]"] = [
            "data:audio/wav;base64," + base64.b64encode(clip).decode() for _, clip in references
        ]
    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=form,
            files={"file": ("reunion.wav", wav, "audio/wav")},
        )
    if response.status_code >= 400:
        log.warning("diarization: la API rechazó la parte: %s", response.text[:300])
    response.raise_for_status()
    return response.json().get("segments") or []


def _reference_clip(pcm: bytes, part_offset_ms: int, segments: list[DiarSegment]) -> bytes | None:
    """Unos segundos de la voz de una persona, del segmento más largo que tenga."""
    longest = max(segments, key=lambda seg: seg.end_ms - seg.start_ms, default=None)
    if longest is None or longest.end_ms - longest.start_ms < REF_MIN_MS:
        return None
    start = (longest.start_ms - part_offset_ms) * BYTES_PER_MS
    length = min(longest.end_ms - longest.start_ms, REF_MAX_MS) * BYTES_PER_MS
    clip = pcm[max(0, start): start + length]
    return pcm16_to_wav(clip, 16000) if len(clip) >= REF_MIN_MS * BYTES_PER_MS else None


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
        if user_id in by_user and len(voices) < MAX_REFERENCES:
            sample, user = by_user[user_id]
            voices.append(KnownVoice(f"voz_{len(voices) + 1}", user.id, user.name, sample.audio_wav))
    return voices


# ── Orquestación ─────────────────────────────────────────────────


async def diarize_meeting(meeting_id: uuid.UUID) -> bool:
    """Separa hablantes con el audio completo. False = no se pudo (sigue lo de siempre)."""
    path = pcm_path(meeting_id)
    if not path.exists() or path.stat().st_size < MIN_AUDIO_MS * BYTES_PER_MS:
        return False
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return False
        config = await resolve_stt(db, meeting.organization_id)
        if config is None or config.provider != "openai":
            return False
        known = await _known_voices(db, meeting)

    known_labels = {voice.label for voice in known}
    diarized: list[DiarSegment] = []
    person_clips: dict[str, bytes] = {}
    people = 0
    part_bytes = PART_MS * BYTES_PER_MS
    with open(path, "rb") as handle:
        offset = 0
        while True:
            pcm = handle.read(part_bytes)
            if len(pcm) < MIN_PART_MS * BYTES_PER_MS:
                break
            part_offset_ms = offset // BYTES_PER_MS
            references = [(voice.label, voice.wav) for voice in known]
            for label, clip in person_clips.items():
                if len(references) >= MAX_REFERENCES:
                    break
                references.append((label, clip))
            names = {name for name, _ in references}
            raw = await _diarize_part(config.api_key, pcm16_to_wav(pcm, 16000), references)

            local: dict[str, str] = {}
            part: list[DiarSegment] = []
            for seg in raw:
                label = str(seg.get("speaker") or "").strip()
                if not label:
                    continue
                if label not in names:
                    if label not in local:
                        people += 1
                        local[label] = f"persona_{people}"
                    label = local[label]
                part.append(
                    DiarSegment(
                        part_offset_ms + int(float(seg.get("start") or 0) * 1000),
                        part_offset_ms + int(float(seg.get("end") or 0) * 1000),
                        label,
                        (seg.get("text") or "").strip(),
                    )
                )
            # Muestras de las personas nuevas, para reconocerlas en las partes siguientes.
            for label in dict.fromkeys(seg.label for seg in part):
                if label.startswith("persona_") and label not in person_clips:
                    clip = _reference_clip(pcm, part_offset_ms, [seg for seg in part if seg.label == label])
                    if clip:
                        person_clips[label] = clip
            diarized += part
            offset += len(pcm)

    if not diarized:
        return False
    await _apply(meeting_id, diarized, {voice.label: voice for voice in known if voice.label in known_labels})
    return True


async def _apply(meeting_id: uuid.UUID, diarized: list[DiarSegment], known: dict[str, KnownVoice]) -> None:
    async with SessionLocal() as db:
        rows = (
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
        if not rows:
            return
        plan = assign_speakers([(row.start_ms, row.end_ms, row.text) for row in rows], diarized)

        await db.execute(
            update(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).values(speaker_id=None)
        )
        await db.execute(delete(Speaker).where(Speaker.meeting_id == meeting_id))

        # Primero todos los hablantes (en orden de aparición), después los tramos:
        # así el insert de los hablantes va antes que las filas que los apuntan.
        speakers: dict[str, Speaker] = {}
        unnamed = 0
        for pieces in plan:
            for label, *_ in pieces:
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

        def speaker_id(label: str | None) -> uuid.UUID | None:
            return speakers[label].id if label is not None else None

        ordered: list[TranscriptSegment] = []
        for row, pieces in zip(rows, plan, strict=True):
            label, text, start, end = pieces[0]
            row.text, row.start_ms, row.end_ms = text, start, end
            row.speaker_hint, row.speaker_id = label, speaker_id(label)
            ordered.append(row)
            for label, text, start, end in pieces[1:]:
                extra = TranscriptSegment(
                    meeting_id=row.meeting_id,
                    organization_id=row.organization_id,
                    seq=row.seq,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    confidence=row.confidence,
                    is_final=True,
                    speaker_hint=label,
                    speaker_id=speaker_id(label),
                )
                db.add(extra)
                ordered.append(extra)
        for seq, segment in enumerate(ordered, start=1):
            segment.seq = seq
        await db.commit()
        log.info("diarization: %s → %s personas, %s tramos", meeting_id, len(speakers), len(ordered))


# ── Nombres con la IA ────────────────────────────────────────────

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
            if confidence >= 0.75:
                speaker.display_name = shown[:200]
                count += 1
            elif confidence >= 0.4:
                speaker.identity_suggestion = {"person_name": shown[:200], "confidence": round(confidence, 2), "source": "ia"}
        await db.commit()
    return count
