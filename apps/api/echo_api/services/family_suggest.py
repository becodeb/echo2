"""La familia de una reunión que terminó sin familia, sacada del título.

En Nordelta muchas reuniones se titulan "Familia Cieri, Salvador · 1/11/2026"
y no se les elige la familia. Al terminar, Echo busca en la sede una familia
(o un alumno) que coincida con el título y se la sugiere a quien la grabó; si
no hay ninguna y el título dice "Familia X", sugiere crearla (02/11/2026).
Nunca asigna sola: la persona confirma con un toque.
"""
import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Family, FamilyMember, Meeting

# " · 1/11/2026", " - 01/11", "(1/11/26)": la fecha que agrega Echo o la persona.
_DATE = re.compile(r"[\s·\-–—(]*\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\)?\s*$")
_WORD = re.compile(r"[a-z0-9ñ]+")
# Palabras que no identifican a nadie.
_STOP = {"familia", "flia", "fam", "de", "del", "la", "las", "los", "y", "e", "con", "reunion", "entrevista", "alumno", "alumna"}


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn" or ch == "̃").replace("ñ", "ñ")


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall(_plain(text)) if word not in _STOP and len(word) > 1}


def title_name(title: str) -> str | None:
    """"Familia Cieri, Salvador · 1/11/2026" -> "Cieri, Salvador"; sin "Familia" adelante, None."""
    text = _DATE.sub("", title.strip()).strip(" ·-–—")
    match = re.match(r"^(?:familia|flia\.?)\s+(.+)$", text, flags=re.IGNORECASE)
    return match.group(1).strip(" ·-–—,") if match else None


async def suggest(db: AsyncSession, meeting: Meeting) -> dict:
    """{"family_id", "family_name", "student_ids"} si una familia coincide; {"create_name"} si hay que crearla; {} si nada."""
    title = _DATE.sub("", meeting.title or "").strip()
    wanted = _tokens(title)
    if not wanted:
        return {}
    families = (
        (await db.execute(select(Family.id, Family.name).where(
                Family.organization_id == meeting.organization_id, Family.deleted_at.is_(None)
            )))
        .all()
    )
    students = (
        await db.execute(
            select(FamilyMember.id, FamilyMember.family_id, FamilyMember.name)
            .join(Family, Family.id == FamilyMember.family_id)
            .where(
                Family.organization_id == meeting.organization_id,
                Family.deleted_at.is_(None),
                FamilyMember.relationship_type == "estudiante",
            )
        )
    ).all()
    names = {family_id: name for family_id, name in families}

    # 1) La familia se llama igual que el título (sin "Familia" ni la fecha).
    exact = [fid for fid, name in families if _tokens(name) and _tokens(name) == wanted]
    # 2) Un alumno cuyo nombre completo está en el título ("Cieri, Salvador").
    by_student: dict[uuid.UUID, list[uuid.UUID]] = {}
    for member_id, family_id, name in students:
        words = _tokens(name)
        if len(words) >= 2 and words <= wanted:
            by_student.setdefault(family_id, []).append(member_id)
    # 3) Todas las palabras del nombre de la familia están en el título ("Familia Pérez" en "Pérez Gómez").
    contained = [fid for fid, name in families if _tokens(name) and _tokens(name) <= wanted]

    for candidates in (exact, list(by_student), contained):
        if len(set(candidates)) == 1:
            family_id = candidates[0]
            return {
                "family_id": str(family_id),
                "family_name": names[family_id],
                "student_ids": [str(sid) for sid in by_student.get(family_id, [])],
            }
        if len(set(candidates)) > 1:
            # Más de una posible: mejor no adivinar.
            return {}
    name = title_name(meeting.title or "")
    return {"create_name": f"Familia {name}"} if name else {}
