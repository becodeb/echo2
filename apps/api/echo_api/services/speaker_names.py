"""Quién es cada persona de la reunión, sin adivinar (docs/plan-correcciones.md §7).

Después de separar a las personas (Scribe), en este orden:

1. **Lo que dijo en voz alta** (§7.3): en los primeros 3 minutos, "hola, soy
   X", "me llamo X", "habla X". X se busca entre participantes, miembros de la
   organización e integrantes de la familia de la reunión; si coincide uno
   solo, se pone ese nombre.
2. **Su voz** (§7.2): la huella de cada persona contra la de "Mi voz" de los
   miembros que la grabaron (services/voiceprint.py). Se nombra solo con
   coincidencia alta y margen; si no, queda como sugerencia.
   Si lo que dijo y la voz no coinciden, gana lo que dijo y la voz queda como
   sugerencia para revisar.
3. Lo que quede sin nombre lo intenta después la IA (diarization.name_speakers),
   con una lista cerrada de roles.

Si la persona lo permite (§7.4), una coincidencia de voz muy alta suma esa
huella a su perfil. Nunca se guardan huellas de quien no grabó su voz.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    FamilyMember,
    Meeting,
    MeetingParticipant,
    OrganizationMember,
    User,
    UserVoiceSample,
)
from . import voiceprint
from .privacy import fold

log = logging.getLogger("echo.speaker_names")

SAID_WITHIN_MS = 3 * 60 * 1000
# Coincidencia de voz desde la que se aprende (más exigente que nombrar).
LEARN_FROM = 0.82
MAX_LEARNED = 20

_SAID = re.compile(
    r"\b(?:soy|me llamo|habla|les habla|te habla|mi nombre es)\s+(?:el |la )?"
    r"([a-zñ]+(?:\s+[a-zñ]+)?)"
)

Row = tuple[str | None, str, int, int]


@dataclass
class Candidate:
    name: str
    user_id: uuid.UUID | None = None
    voice: np.ndarray | None = None
    sample_id: uuid.UUID | None = None
    learn: bool = False


@dataclass
class Naming:
    """Lo que se sabe de una persona de la reunión."""

    name: str
    user_id: uuid.UUID | None
    source: str  # voz | dijo
    accepted: bool  # True: se pone el nombre; False: sugerencia
    score: float = 1.0
    extra: dict = field(default_factory=dict)

    def suggestion(self) -> dict:
        return {
            "person_name": self.name,
            "user_id": str(self.user_id) if self.user_id else None,
            "confidence": round(self.score, 2),
            "source": self.source,
            **self.extra,
        }


def said_names(rows: list[Row], candidates: list[Candidate]) -> dict[str, Candidate]:
    """"Hola, soy X" en los primeros minutos → la persona que lo dijo es X.

    Solo si X coincide con UN candidato (por nombre de pila, o nombre y
    apellido). Dos personas que dicen ser la misma, o un nombre que tienen
    dos candidatos, no se nombran.
    """
    found: dict[str, Candidate] = {}
    for label, text, start, _ in rows:
        if label is None or start > SAID_WITHIN_MS:
            continue
        for match in _SAID.finditer(fold(text)):
            words = match.group(1).split()
            hits = [c for c in candidates if _names(c.name, words)]
            unique = {(c.name, c.user_id) for c in hits}
            if len(unique) == 1:
                found.setdefault(label, hits[0])
                break
    owners: dict[tuple, list[str]] = {}
    for label, candidate in found.items():
        owners.setdefault((candidate.name, candidate.user_id), []).append(label)
    return {label: c for label, c in found.items() if len(owners[(c.name, c.user_id)]) == 1}


def _names(full_name: str, said: list[str]) -> bool:
    parts = fold(full_name).split()
    if not parts or not said:
        return False
    if said[0] != parts[0]:
        return False
    return len(said) == 1 or said[1] in parts[1:] or len(parts) == 1


def decide(
    rows: list[Row], candidates: list[Candidate], prints: dict[str, np.ndarray]
) -> dict[str, Naming]:
    """Junta lo que dijo cada persona y su voz (puro, sin base ni audio)."""
    out: dict[str, Naming] = {}
    for label, candidate in said_names(rows, candidates).items():
        out[label] = Naming(candidate.name, candidate.user_id, "dijo", True)

    with_voice = [c for c in candidates if c.voice is not None]
    people = [label for label in prints]
    if with_voice and people:
        scores = np.array([[float(np.dot(prints[p], c.voice)) for c in with_voice] for p in people])
        for match in voiceprint.assign(scores, people=people):
            candidate = with_voice[match.candidate]
            heard = Naming(candidate.name, candidate.user_id, "voz", match.accepted, match.score)
            current = out.get(match.person)
            if current is None:
                out[match.person] = heard
            elif current.user_id != candidate.user_id:
                # Dijo una cosa y la voz dice otra: gana lo dicho, y la voz
                # queda a la vista para que alguien lo revise.
                current.extra = {"voice_says": candidate.name, "voice_score": match.score}

    # Nadie queda nombrado dos veces: si lo dicho y la voz chocan entre
    # personas distintas, las dos pasan a sugerencia.
    by_user: dict[uuid.UUID, list[str]] = {}
    for label, naming in out.items():
        if naming.accepted and naming.user_id:
            by_user.setdefault(naming.user_id, []).append(label)
    for labels in by_user.values():
        if len(labels) > 1:
            for label in labels:
                out[label].accepted = False
    return out


async def _candidates(db, meeting: Meeting) -> list[Candidate]:
    members = (
        await db.execute(
            select(User.id, User.name)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == meeting.organization_id)
        )
    ).all()
    samples = {
        sample.user_id: sample
        for sample in (
            await db.execute(
                select(UserVoiceSample).where(
                    UserVoiceSample.user_id.in_([user_id for user_id, _ in members] or [uuid.uuid4()]),
                    UserVoiceSample.embedding_model == voiceprint.MODEL_NAME,
                )
            )
        ).scalars()
    }
    out = []
    for user_id, name in members:
        sample = samples.get(user_id)
        voice = np.asarray(sample.embedding, dtype=np.float32) if sample is not None and sample.embedding is not None else None
        out.append(Candidate(name or "", user_id, voice, sample.id if sample else None,
                             bool(sample and sample.learn_from_meetings)))
    member_names = {fold(c.name) for c in out}
    for name, user_id in (
        await db.execute(
            select(MeetingParticipant.name, MeetingParticipant.user_id).where(MeetingParticipant.meeting_id == meeting.id)
        )
    ).all():
        if name and fold(name) not in member_names:
            out.append(Candidate(name, user_id))
    if meeting.family_id:
        for (name,) in (
            await db.execute(select(FamilyMember.name).where(FamilyMember.family_id == meeting.family_id))
        ).all():
            if name and fold(name) not in member_names:
                out.append(Candidate(name))
    return [c for c in out if c.name.strip()]


async def resolve(meeting_id: uuid.UUID, rows: list[Row], pcm: np.ndarray | None) -> dict[str, Naming]:
    """Nombres de las personas de la reunión. Nunca corta la pasada final."""
    try:
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None:
                return {}
            candidates = await _candidates(db, meeting)
        prints: dict[str, np.ndarray] = {}
        if pcm is not None and any(c.voice is not None for c in candidates) and voiceprint.available():
            turns = [(label, start, end) for label, _, start, end in rows]
            prints = await asyncio.to_thread(voiceprint.people_prints, pcm, turns)
        names = decide(rows, candidates, prints)
        await _learn(names, prints, candidates)
        if names:
            log.info("nombres de %s: %s", meeting_id,
                     {label: (n.source, n.accepted, n.score) for label, n in names.items()})
        return names
    except Exception:  # noqa: BLE001 - sin nombres queda "Persona 1"
        log.exception("no se pudieron poner los nombres de %s", meeting_id)
        return {}


async def _learn(names: dict[str, Naming], prints: dict[str, np.ndarray], candidates: list[Candidate]) -> None:
    """§7.4: suma la huella de la reunión al perfil de quien lo permitió."""
    by_user = {c.user_id: c for c in candidates if c.user_id and c.sample_id and c.learn}
    learned = [
        (by_user[naming.user_id], prints[label])
        for label, naming in names.items()
        if naming.source == "voz" and naming.accepted and naming.score >= LEARN_FROM
        and naming.user_id in by_user and label in prints
    ]
    if not learned:
        return
    async with SessionLocal() as db:
        for candidate, vector in learned:
            sample = await db.get(UserVoiceSample, candidate.sample_id)
            if sample is None or sample.embedding is None or not sample.learn_from_meetings:
                continue
            weight = min(sample.learned_count + 1, MAX_LEARNED)
            profile = np.asarray(sample.embedding, dtype=np.float32) * weight + vector
            sample.embedding = voiceprint.to_list(profile / float(np.linalg.norm(profile)))
            sample.learned_count += 1
        await db.commit()


async def fingerprint_sample(wav_pcm: bytes) -> list[float] | None:
    """La huella de una muestra de "Mi voz" (PCM16 mono 16 kHz)."""
    samples = np.frombuffer(wav_pcm[: len(wav_pcm) // 2 * 2], dtype=np.int16)
    return voiceprint.to_list(await asyncio.to_thread(voiceprint.embed, samples))
