"""Quién es cada persona de la reunión, sin adivinar (docs/plan-correcciones.md §7).

Después de separar a las personas (Scribe), en este orden:

1. **Lo que dijo en voz alta** (§7.3): en los primeros 3 minutos, "hola, soy
   X", "me llamo X", "habla X". X se busca entre participantes, miembros de la
   organización e integrantes de la familia de la reunión; si coincide uno
   solo, se pone ese nombre.
2. **Su voz** (§7.2): la huella de cada persona contra la de "Mi voz" de
   quienes pueden haber estado (`could_have_been`): quien la grabó, la gente
   del colegio que figura como que estuvo y los participantes cuyo nombre es
   el de un solo miembro. Nunca contra toda la sede. La voz sola no pone el
   nombre: con coincidencia alta y margen queda "¿Puede ser X?" (sin
   porcentaje); si no, nada. Quien ya dijo "no es X" no se vuelve a sugerir
   en esa reunión.
   Si lo que dijo y la voz no coinciden, gana lo que dijo y la voz queda como
   sugerencia para revisar.
3. Lo que quede sin nombre lo intenta después la IA (diarization.name_speakers),
   con una lista cerrada de roles.

Echo ya no suma huellas de las reuniones al perfil (§7.4): aprendía de lo
que adivinaba y el perfil terminaba pareciéndose a cualquiera (27/10). Nunca
se guardan huellas de quien no grabó su voz.
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
# meeting.meta: usuarios que alguien descartó ("no es X") en esa reunión.
VOICE_REJECTED = "voice_rejected"

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
        out = {
            "person_name": self.name,
            "user_id": str(self.user_id) if self.user_id else None,
            "source": self.source,
            **self.extra,
        }
        # Por la voz no hay porcentaje: el parecido no dice qué tan seguro es.
        if self.source != "voz":
            out["confidence"] = round(self.score, 2)
        return out


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
            heard = Naming(candidate.name, candidate.user_id, "voz", False, match.score)
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


def could_have_been(
    created_by: uuid.UUID | None,
    members: list[tuple[uuid.UUID, str | None]],
    participants: list[tuple[str | None, uuid.UUID | None]],
) -> set[uuid.UUID]:
    """Quiénes del colegio pueden haber estado en la reunión.

    Quien la grabó, los que figuran como que estuvieron y los participantes
    cargados a mano cuyo nombre es el de un solo miembro ("Natalia" sirve si
    hay una sola Natalia). Contra toda la sede, la voz se equivocaba 10 de
    cada 14 veces (27/10).
    """
    present = {created_by} | {user_id for _, user_id in participants if user_id}
    for name, user_id in participants:
        if user_id or not name:
            continue
        words = fold(name).split()
        hits = {member_id for member_id, member_name in members if _names(member_name or "", words)}
        if len(hits) == 1:
            present |= hits
    return present & {member_id for member_id, _ in members}


async def _candidates(db, meeting: Meeting) -> list[Candidate]:
    members = (
        await db.execute(
            select(User.id, User.name)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == meeting.organization_id)
        )
    ).all()
    participants = (
        await db.execute(
            select(MeetingParticipant.name, MeetingParticipant.user_id).where(MeetingParticipant.meeting_id == meeting.id)
        )
    ).all()
    rejected = {str(user_id) for user_id in (meeting.meta or {}).get(VOICE_REJECTED, [])}
    present = {
        user_id for user_id in could_have_been(meeting.created_by, members, participants) if str(user_id) not in rejected
    }
    samples = {
        sample.user_id: sample
        for sample in (
            await db.execute(
                select(UserVoiceSample).where(
                    UserVoiceSample.user_id.in_(present or [uuid.uuid4()]),
                    UserVoiceSample.embedding_model == voiceprint.MODEL_NAME,
                    UserVoiceSample.duration_ms >= voiceprint.MIN_SAMPLE_MS,
                )
            )
        ).scalars()
    }
    out = []
    for user_id, name in members:
        sample = samples.get(user_id)
        voice = np.asarray(sample.embedding, dtype=np.float32) if sample is not None and sample.embedding is not None else None
        out.append(Candidate(name or "", user_id, voice))
    member_names = {fold(c.name) for c in out}
    for name, user_id in participants:
        if name and fold(name) not in member_names:
            out.append(Candidate(name, user_id))
    if meeting.family_id:
        for (name,) in (
            await db.execute(select(FamilyMember.name).where(FamilyMember.family_id == meeting.family_id))
        ).all():
            if name and fold(name) not in member_names:
                out.append(Candidate(name))
    return [c for c in out if c.name.strip()]


async def resolve(
    meeting_id: uuid.UUID, rows: list[Row], pcm: np.ndarray | None, prints: dict[str, np.ndarray] | None = None
) -> dict[str, Naming]:
    """Nombres de las personas de la reunión. Nunca corta la pasada final.

    `prints`: la huella de cada persona, si ya se sacó al unir los tramos
    (services/final_chunks.py); si no, se saca acá con hasta 30 s de cada una.
    """
    try:
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None:
                return {}
            candidates = await _candidates(db, meeting)
        if not any(c.voice is not None for c in candidates):
            prints = {}
        elif prints is None:
            prints = {}
            if pcm is not None and voiceprint.available():
                turns = [(label, start, end) for label, _, start, end in rows]
                prints = await asyncio.to_thread(voiceprint.people_prints, pcm, turns)
        names = decide(rows, candidates, prints)
        if names:
            log.info("nombres de %s: %s", meeting_id,
                     {label: (n.source, n.accepted, n.score) for label, n in names.items()})
        return names
    except Exception:  # noqa: BLE001 - sin nombres queda "Persona 1"
        log.exception("no se pudieron poner los nombres de %s", meeting_id)
        return {}


async def fingerprint_sample(wav_pcm: bytes) -> list[float] | None:
    """La huella de una muestra de "Mi voz" (PCM16 mono 16 kHz)."""
    samples = np.frombuffer(wav_pcm[: len(wav_pcm) // 2 * 2], dtype=np.int16)
    return voiceprint.to_list(await asyncio.to_thread(voiceprint.embed, samples))
