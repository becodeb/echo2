"""Mover a alguien de una sede a otra: desde el Panel de Becode o pidiéndoselo a Echo.

Mover es salir de una sede y quedar en otra en un solo paso, con su rol, puesto y
niveles. Si ya era de la de destino, conserva lo que tiene ahí y solo sale de la
otra. Sus reuniones y tareas no se mudan: son de la sede donde pasaron.

Echo nunca mueve por su cuenta: del chat sale una propuesta con la persona y las
sedes ya resueltas, y lo hace el botón de confirmar, que pega en este mismo endpoint.
"""
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    LEVELS,
    ActionItem,
    InternalGroup,
    InternalGroupMember,
    Meeting,
    MemberLevelAccess,
    Organization,
    OrganizationMember,
    User,
)
from ..services.audit import audit
from ..services.positions import Position, is_admin_role, org_positions
from .admin import get_superadmin
from .orgs import _commit, _group_by_name, _require_another_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Una reunión "en vivo" sin movimiento hace rato quedó colgada: esa no frena nada.
LIVE_WINDOW = timedelta(hours=3)


class MoveIn(BaseModel):
    from_organization_id: uuid.UUID
    to_organization_id: uuid.UUID


class MoveOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    from_id: uuid.UUID
    from_name: str
    to_id: uuid.UUID
    to_name: str
    # Ya era de la sede de destino: conserva lo de ahí y solo sale de la otra.
    already_there: bool
    # Con qué queda en la de destino.
    role: str
    position: str | None
    levels: dict[str, str]
    # Lo que no se muda: queda en la de origen.
    meetings_left: int
    tasks_left: int


async def _person(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    return user


async def _campus(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if not org or org.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sede no encontrada")
    if org.is_personal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Una cuenta individual es de una sola persona")
    return org


async def _member(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> OrganizationMember | None:
    return (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def _levels(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    found = dict(
        (
            await db.execute(
                select(MemberLevelAccess.level, MemberLevelAccess.access).where(
                    MemberLevelAccess.organization_id == org_id, MemberLevelAccess.user_id == user_id
                )
            )
        ).all()
    )
    return {level: found[level] for level in LEVELS if level in found}


async def _position_in(db: AsyncSession, position_id: str | None, source_id: uuid.UUID, target_id: uuid.UUID) -> Position | None:
    """El mismo puesto en la otra sede. Uno propio de la sede solo pasa si allá hay uno con ese nombre."""
    position = next((item for item in await org_positions(db, source_id) if item.id == position_id), None)
    if position is None or not position.custom:
        return position
    return next(
        (item for item in await org_positions(db, target_id) if item.custom and item.label.casefold() == position.label.casefold()),
        None,
    )


async def _plan(db: AsyncSession, user: User, source: Organization, target: Organization) -> MoveOut:
    """Lo que pasaría, o el motivo por el que no se puede. No cambia nada."""
    if source.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elegí dos sedes distintas")
    member = await _member(db, source.id, user.id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{user.name} no es de {source.name}")
    if member.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{user.name} creó {source.name}: desde ahí no se puede mover")
    if is_admin_role(member.role):
        await _require_another_admin(db, source.id, member.id)
    recording = (
        await db.execute(
            select(func.count()).select_from(Meeting).where(
                Meeting.organization_id == source.id,
                Meeting.created_by == user.id,
                Meeting.deleted_at.is_(None),
                Meeting.status.in_(("live", "paused")),
                Meeting.updated_at > datetime.now(UTC) - LIVE_WINDOW,
            )
        )
    ).scalar_one()
    if recording:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{user.name} tiene una reunión en curso en {source.name}: movelo cuando termine")

    existing = await _member(db, target.id, user.id)
    if existing:
        kept = next((item for item in await org_positions(db, target.id) if item.id == existing.position), None)
        role, levels = existing.role, await _levels(db, target.id, user.id)
    else:
        kept = await _position_in(db, member.position, source.id, target.id)
        role, levels = member.role, await _levels(db, source.id, user.id)

    meetings_left = (
        await db.execute(
            select(func.count()).select_from(Meeting).where(
                Meeting.organization_id == source.id, Meeting.created_by == user.id, Meeting.deleted_at.is_(None)
            )
        )
    ).scalar_one()
    tasks_left = (
        await db.execute(
            select(func.count()).select_from(ActionItem).where(
                ActionItem.organization_id == source.id,
                ActionItem.assignee_user_id == user.id,
                ActionItem.status.in_(("pending", "in_progress")),
            )
        )
    ).scalar_one()
    return MoveOut(
        user_id=user.id,
        name=user.name,
        email=user.email,
        from_id=source.id,
        from_name=source.name,
        to_id=target.id,
        to_name=target.name,
        already_there=existing is not None,
        role=role,
        position=kept.label if kept else None,
        levels=levels,
        meetings_left=meetings_left,
        tasks_left=tasks_left,
    )


@router.get("/people/{user_id}/move", response_model=MoveOut)
async def preview_move(
    user_id: uuid.UUID,
    from_organization_id: uuid.UUID,
    to_organization_id: uuid.UUID,
    _: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await _plan(
        db, await _person(db, user_id), await _campus(db, from_organization_id), await _campus(db, to_organization_id)
    )


@router.post("/people/{user_id}/move", response_model=MoveOut)
async def move_person(
    user_id: uuid.UUID,
    data: MoveIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    user = await _person(db, user_id)
    source = await _campus(db, data.from_organization_id)
    target = await _campus(db, data.to_organization_id)
    plan = await _plan(db, user, source, target)
    member = await _member(db, source.id, user.id)

    if not plan.already_there:
        carried = await _position_in(db, member.position, source.id, target.id)
        db.add(
            OrganizationMember(
                organization_id=target.id, user_id=user.id, role=member.role, position=carried.id if carried else None
            )
        )
        for level, access in plan.levels.items():
            db.add(MemberLevelAccess(organization_id=target.id, user_id=user.id, level=level, access=access))
        # Los grupos abren reuniones internas: solo los que allá ya existen, más el de su puesto.
        names = set(
            (
                await db.execute(
                    select(InternalGroup.name)
                    .join(InternalGroupMember, InternalGroupMember.group_id == InternalGroup.id)
                    .where(InternalGroupMember.organization_id == source.id, InternalGroupMember.user_id == user.id)
                )
            ).scalars()
        ) & set((await db.execute(select(InternalGroup.name).where(InternalGroup.organization_id == target.id))).scalars())
        if carried and carried.group:
            names.add(carried.group)
        for name in names:
            group = await _group_by_name(db, target.id, name)
            db.add(InternalGroupMember(group_id=group.id, organization_id=target.id, user_id=user.id))

    await db.execute(
        delete(MemberLevelAccess).where(MemberLevelAccess.organization_id == source.id, MemberLevelAccess.user_id == user.id)
    )
    await db.execute(
        delete(InternalGroupMember).where(InternalGroupMember.organization_id == source.id, InternalGroupMember.user_id == user.id)
    )
    await db.delete(member)
    detail = {"user_id": str(user.id), "email": user.email, "from": source.name, "to": target.name, "by": admin.email}
    await audit(db, source.id, admin.id, "admin.member_moved_out", "user", str(user.id), detail=detail)
    await audit(db, target.id, admin.id, "admin.member_moved_in", "user", str(user.id), detail=detail)
    await _commit(db)
    return plan


# ── Pedírselo a Echo ─────────────────────────────────────────────

MOVE_SYSTEM = """Recibís un mensaje de quien administra Echo, una plataforma de reuniones de
colegios. Decidí si está pidiendo mover (pasar, cambiar, transferir) a una PERSONA de una sede a otra.

Sedes que existen: {sedes}

Devolvé este JSON:
{{"move": true o false, "person": "la persona, tal como la escribió (nombre, usuario o mail)", "from": "sede de origen, o null", "to": "sede de destino, o null"}}

- "move" es false si pregunta por reuniones, tareas, familias o cualquier otra cosa
  ("¿qué pasó en Puertos?", "pasame las tareas de Nordelta").
- "from" y "to" son nombres de la lista de sedes, o null si no lo dijo. No los adivines."""

_MOVE_VERB = re.compile(r"\b(mov|muev|pas[aeo]|transfer|traslad|reubic|cambi)\w*")


def _plain(text: str) -> str:
    """Sin tildes ni mayúsculas: "Analía" y "analia" son la misma."""
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    ).casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", _plain(text))


async def campus_list(db: AsyncSession) -> list[Organization]:
    return list(
        (
            await db.execute(
                select(Organization)
                .where(Organization.deleted_at.is_(None), Organization.is_personal.is_(False))
                .order_by(Organization.name)
            )
        ).scalars()
    )


def looks_like_move(question: str, campuses: list[Organization]) -> bool:
    """Filtro barato, antes de gastar una llamada al modelo: un verbo de mover y una sede."""
    plain = _plain(question)
    if not _MOVE_VERB.search(plain):
        return False
    mentioned = {word for org in campuses for word in _words(org.name) if len(word) > 3}
    words = set(_words(plain))
    return "sede" in words or bool(words & mentioned)


def _find_campus(text: str | None, campuses: list[Organization]) -> Organization | None:
    wanted = _plain(text or "").strip()
    if not wanted:
        return None
    exact = [org for org in campuses if _plain(org.name) == wanted]
    found = exact or [org for org in campuses if wanted in _plain(org.name) or _plain(org.name) in wanted]
    return found[0] if len(found) == 1 else None


def _matches(query: str, user: User) -> bool:
    words = _words(query)
    if not words:
        return False
    # "Analía Oliver - Northfield Puertos": lo que va después del guion es la sede.
    name = _words(user.name.split(" - ")[0])
    if all(any(part.startswith(word) for part in name) for word in words):
        return True
    if len(words) > 1:
        return False
    word = words[0]
    # El usuario del mail, o inicial + apellido ("aoliver").
    return word in _plain(user.email.split("@")[0]) or any(
        word == first[0] + last for first in name for last in name if first != last
    )


async def _find_people(db: AsyncSession, query: str) -> list[User]:
    users = list((await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(User.name))).scalars())
    wanted = _plain(query).strip()
    # Un mail escrito entero no da lugar a dudas, aunque otro se parezca.
    exact = [user for user in users if _plain(user.email) == wanted]
    return exact or [user for user in users if _matches(query, user)]


@dataclass
class MoveAnswer:
    answer: str
    move: MoveOut | None = None
    # Para elegir cuando hay más de una posibilidad: (qué se ve, qué se le vuelve a pedir a Echo).
    options: list[tuple[str, str]] = field(default_factory=list)


async def answer_move(db: AsyncSession, campuses: list[Organization], parsed: dict) -> MoveAnswer:
    """De lo que entendió el modelo a una propuesta: la persona y las sedes se buscan acá, no las inventa él."""
    person = str(parsed.get("person") or "").strip()
    example = "«mové a Ana Gómez de Nordelta a Puertos»"
    if not person:
        return MoveAnswer(f"Decime a quién querés mover, por ejemplo: {example}.")
    target = _find_campus(parsed.get("to"), campuses)
    if target is None:
        return MoveAnswer(f"¿A qué sede movemos a **{person}**? Las que hay: {', '.join(org.name for org in campuses)}.")

    people = await _find_people(db, person)
    if not people:
        return MoveAnswer(f"No encontré a nadie que coincida con **{person}**. Fijate el nombre o el mail en Panel de Becode → Usuarios.")
    source = _find_campus(parsed.get("from"), campuses)
    if len(people) > 1:
        origin = f" de {source.name}" if source else ""
        return MoveAnswer(
            f"Hay {len(people)} personas que coinciden con **{person}**. ¿A cuál movemos?",
            options=[
                (f"{user.name} · {user.email}", f"Mové a {user.email}{origin} a {target.name}")
                for user in people[:6]
            ],
        )

    user = people[0]
    if source is None:
        own = (
            await db.execute(
                select(Organization)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .where(
                    OrganizationMember.user_id == user.id,
                    OrganizationMember.role != "owner",
                    Organization.is_personal.is_(False),
                    Organization.deleted_at.is_(None),
                    Organization.id != target.id,
                )
                .order_by(Organization.name)
            )
        ).scalars().all()
        if not own:
            return MoveAnswer(f"**{user.name}** no tiene otra sede de la que salir para pasar a {target.name}.")
        if len(own) > 1:
            return MoveAnswer(
                f"**{user.name}** está en varias sedes. ¿De cuál sale?",
                options=[(org.name, f"Mové a {user.email} de {org.name} a {target.name}") for org in own],
            )
        source = own[0]

    try:
        plan = await _plan(db, user, source, target)
    except HTTPException as exc:
        return MoveAnswer(str(exc.detail))
    if plan.already_there:
        return MoveAnswer(f"**{user.name}** ya está en **{target.name}**, así que solo sale de **{source.name}**.", plan)
    return MoveAnswer(f"Voy a mover a **{user.name}** de **{source.name}** a **{target.name}**.", plan)
