"""Gestión de la organización: miembros, invitaciones, diccionario."""
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import ROLE_ORDER, OrgContext, get_org_context
from ..models import (
    DEFAULT_GROUPS,
    LEVELS,
    ROLES,
    CustomPosition,
    InternalGroup,
    InternalGroupMember,
    MemberLevelAccess,
    OrganizationInvite,
    OrganizationMember,
    OrgDictionaryEntry,
    RefreshToken,
    User,
    UserVoiceSample,
)
from ..services.access import rank_of
from ..services.audit import audit
from ..services.positions import Position, custom_position, guess_position, is_admin_role, org_positions

router = APIRouter(prefix="/api/org", tags=["org"])


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_color: str
    avatar_url: str | None = None
    job_title: str | None
    role: str


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == ctx.org_id)
            .order_by(User.name)
        )
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            name=u.name,
            email=u.email,
            avatar_color=u.avatar_color,
            avatar_url=u.avatar_url,
            job_title=u.job_title,
            role=m.role,
        )
        for m, u in rows
    ]


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(default="member")


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    token: str
    expires_at: datetime


@router.post("/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    data: InviteIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("admin")
    if data.role not in ROLES or data.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rol inválido")

    invite = OrganizationInvite(
        organization_id=ctx.org_id,
        email=data.email.lower(),
        role=data.role,
        token=secrets.token_urlsafe(32),
        invited_by=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    await audit(db, ctx.org_id, ctx.user.id, "org.invite_created", "invite", data.email)
    await db.commit()
    await db.refresh(invite)
    return InviteOut(
        id=invite.id, email=invite.email, role=invite.role, token=invite.token,
        expires_at=invite.expires_at,
    )


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    ctx.require_role("admin")
    rows = (
        (
            await db.execute(
                select(OrganizationInvite).where(
                    OrganizationInvite.organization_id == ctx.org_id,
                    OrganizationInvite.accepted_at.is_(None),
                    OrganizationInvite.expires_at > datetime.now(UTC),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        InviteOut(id=i.id, email=i.email, role=i.role, token=i.token, expires_at=i.expires_at)
        for i in rows
    ]


class RoleIn(BaseModel):
    role: str


@router.patch("/members/{member_id}", response_model=MemberOut)
async def change_role(
    member_id: uuid.UUID,
    data: RoleIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    if data.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rol inválido")
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.id == member_id,
                OrganizationMember.organization_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
    if member.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede cambiar el rol del owner")
    if data.role == "owner":
        ctx.require_role("owner")
    if member.user_id == ctx.user.id and ROLE_ORDER.get(data.role, 0) > ROLE_ORDER.get(member.role, 0):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu propio rol lo cambia otra persona que administre la sede")
    if is_admin_role(member.role) and not is_admin_role(data.role):
        await _require_another_admin(db, ctx.org_id, member.id)
    previous = member.role
    member.role = data.role
    await audit(
        db, ctx.org_id, ctx.user.id, "org.role_changed", "member", str(member_id),
        detail={"user_id": str(member.user_id), "from": previous, "to": data.role, "by": ctx.user.email},
    )
    await db.commit()
    user = await db.get(User, member.user_id)
    return MemberOut(
        id=member.id, user_id=user.id, name=user.name, email=user.email,
        avatar_color=user.avatar_color, job_title=user.job_title, role=member.role,
    )


@router.delete("/members/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.id == member_id,
                OrganizationMember.organization_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
    if member.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede eliminar al owner")
    if is_admin_role(member.role):
        await _require_another_admin(db, ctx.org_id, member.id)
    await db.delete(member)
    await audit(
        db, ctx.org_id, ctx.user.id, "org.member_removed", "member", str(member_id),
        detail={"user_id": str(member.user_id), "role": member.role, "by": ctx.user.email},
    )
    await db.commit()


async def _require_another_admin(db: AsyncSession, org_id: uuid.UUID, member_id: uuid.UUID) -> None:
    """Corta si sacarle la administración a este miembro deja la sede sin nadie que la administre."""
    others = (
        await db.execute(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.id != member_id,
                OrganizationMember.role.in_(("admin", "owner")),
            )
        )
    ).scalar()
    if not others:
        raise HTTPException(status.HTTP_409_CONFLICT, "La sede se quedaría sin nadie que la administre")


# ── Usuarios de la sede: puesto y niveles ────────────────────────
#
# Quien administra la sede ve a todos y les elige el puesto (DOE, docente,
# directivo...) y los niveles. El puesto se traduce a rol de sede + acceso por
# nivel + grupo interno (services/positions.py), así que quién ve qué y a
# quién se le asignan tareas sigue saliendo de services/access.py.

ACCESS_ORDER = {"limitado": 1, "tutor": 1, "direccion": 2, "adviser": 3, "total": 4}


def _require_user_manager(ctx: OrgContext) -> None:
    if not (is_admin_role(ctx.role) or ctx.user.is_superadmin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo quien administra la sede ve y cambia los usuarios")


class PositionOut(BaseModel):
    id: str
    label: str
    description: str
    # Dirección de la sede ve todo: los niveles no le cambian nada.
    needs_levels: bool
    # Los propios de la sede: se editan y se borran; los fijos no.
    custom: bool = False
    is_admin: bool = False
    access: str = "limitado"
    group: str | None = None
    watch_group_ids: list[uuid.UUID] = Field(default_factory=list)
    # Cuánta gente lo tiene: para pedir a qué puesto pasarla antes de borrarlo.
    holders: int = 0


class UserGroupOut(BaseModel):
    id: uuid.UUID
    name: str


class OrgUserOut(BaseModel):
    member_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_color: str
    avatar_url: str | None = None
    role: str
    # El que se eligió; nulo si nadie lo eligió todavía.
    position: str | None
    # Lo que parece por sus permisos, para mostrar mientras no se elija.
    guessed_position: str | None
    levels: dict[str, str]
    groups: list[UserGroupOut]
    # Última vez que abrió Echo (cada entrada o renovación de la sesión).
    last_seen_at: datetime | None
    has_voice: bool
    is_owner: bool


class OrgUsersOut(BaseModel):
    positions: list[PositionOut]
    levels: list[str]
    # Los grupos internos de la sede, para armar un puesto propio.
    groups: list[UserGroupOut] = Field(default_factory=list)
    users: list[OrgUserOut]


async def _org_users(db: AsyncSession, org_id: uuid.UUID, only: uuid.UUID | None = None) -> list[OrgUserOut]:
    query = (
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == org_id)
        .order_by(User.name)
    )
    if only is not None:
        query = query.where(User.id == only)
    members = (await db.execute(query)).all()
    ids = [user.id for _, user in members]
    if not ids:
        return []
    known = {position.id for position in await org_positions(db, org_id)}
    levels: dict[uuid.UUID, dict[str, str]] = {}
    for row in (
        await db.execute(
            select(MemberLevelAccess).where(
                MemberLevelAccess.organization_id == org_id, MemberLevelAccess.user_id.in_(ids)
            )
        )
    ).scalars():
        levels.setdefault(row.user_id, {})[row.level] = row.access
    groups: dict[uuid.UUID, list[UserGroupOut]] = {}
    for user_id, group_id, name in (
        await db.execute(
            select(InternalGroupMember.user_id, InternalGroup.id, InternalGroup.name)
            .join(InternalGroup, InternalGroup.id == InternalGroupMember.group_id)
            .where(InternalGroupMember.organization_id == org_id, InternalGroupMember.user_id.in_(ids))
            .order_by(InternalGroup.name)
        )
    ).all():
        groups.setdefault(user_id, []).append(UserGroupOut(id=group_id, name=name))
    last_seen = dict(
        (
            await db.execute(
                select(RefreshToken.user_id, func.max(RefreshToken.created_at))
                .where(RefreshToken.user_id.in_(ids))
                .group_by(RefreshToken.user_id)
            )
        ).all()
    )
    voices = set(
        (await db.execute(select(UserVoiceSample.user_id).where(UserVoiceSample.user_id.in_(ids)))).scalars()
    )
    out = []
    for member, user in members:
        user_levels = {level: levels[user.id][level] for level in LEVELS if level in levels.get(user.id, {})}
        user_groups = groups.get(user.id, [])
        out.append(
            OrgUserOut(
                member_id=member.id,
                user_id=user.id,
                name=user.name,
                email=user.email,
                avatar_color=user.avatar_color,
                avatar_url=user.avatar_url,
                role=member.role,
                position=member.position if member.position in known else None,
                guessed_position=guess_position(
                    member.role, list(user_levels.values()), {group.name for group in user_groups}
                ),
                levels=user_levels,
                groups=user_groups,
                last_seen_at=last_seen.get(user.id),
                has_voice=user.id in voices,
                is_owner=member.role == "owner",
            )
        )
    return out


async def _positions_out(db: AsyncSession, org_id: uuid.UUID) -> list[PositionOut]:
    holders = dict(
        (
            await db.execute(
                select(OrganizationMember.position, func.count())
                .where(OrganizationMember.organization_id == org_id, OrganizationMember.position.is_not(None))
                .group_by(OrganizationMember.position)
            )
        ).all()
    )
    return [
        PositionOut(
            id=p.id, label=p.label, description=p.description, needs_levels=not is_admin_role(p.role),
            custom=p.custom, is_admin=is_admin_role(p.role), access=p.access, group=p.group,
            watch_group_ids=list(p.watch_group_ids), holders=holders.get(p.id, 0),
        )
        for p in await org_positions(db, org_id)
    ]


@router.get("/users", response_model=OrgUsersOut)
async def list_org_users(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    _require_user_manager(ctx)
    groups = (
        await db.execute(
            select(InternalGroup.id, InternalGroup.name)
            .where(InternalGroup.organization_id == ctx.org_id)
            .order_by(InternalGroup.name)
        )
    ).all()
    return OrgUsersOut(
        positions=await _positions_out(db, ctx.org_id),
        levels=list(LEVELS),
        groups=[UserGroupOut(id=group_id, name=name) for group_id, name in groups],
        users=await _org_users(db, ctx.org_id),
    )


class PositionIn(BaseModel):
    position: str
    levels: list[str] = Field(default_factory=list, max_length=len(LEVELS))


async def _group_by_name(db: AsyncSession, org_id: uuid.UUID, name: str) -> InternalGroup:
    """El grupo del puesto; si la sede no lo tiene, se crea (con los de siempre si no tenía ninguno)."""
    groups = {
        group.name: group
        for group in (await db.execute(select(InternalGroup).where(InternalGroup.organization_id == org_id))).scalars()
    }
    if name in groups:
        return groups[name]
    # Sin ningún grupo, Reuniones internas crearía los de siempre la primera vez;
    # si acá se crea solo "DOE", después no los crearía nunca.
    for default in DEFAULT_GROUPS if not groups else ():
        if default != name:
            db.add(InternalGroup(organization_id=org_id, name=default))
    group = InternalGroup(organization_id=org_id, name=name)
    db.add(group)
    await db.flush()
    return group


async def _apply_position(
    db: AsyncSession,
    ctx: OrgContext,
    member: OrganizationMember,
    position: Position,
    chosen: list[str],
    old: Position | None,
) -> dict:
    """Le da a alguien los permisos de un puesto. `old` es el que tenía (para sacarle su grupo).

    Devuelve el detalle para la auditoría. Las validaciones (dueño, la
    sede sin admin, darse más permisos uno mismo) las hace quien llama.
    """
    user_id = member.user_id
    new_role = "owner" if member.role == "owner" else position.role
    rows = {
        row.level: row
        for row in (
            await db.execute(
                select(MemberLevelAccess).where(
                    MemberLevelAccess.organization_id == ctx.org_id, MemberLevelAccess.user_id == user_id
                )
            )
        ).scalars()
    }
    before_levels = {level: rows[level].access for level in LEVELS if level in rows}
    after_levels = {level: position.access for level in chosen}
    memberships = await _memberships(db, ctx.org_id, user_id)

    before = {"position": member.position, "role": member.role, "levels": before_levels}
    member.role = new_role
    member.position = position.id
    for level, row in rows.items():
        if level not in after_levels:
            await db.delete(row)
    for level, access in after_levels.items():
        if level in rows:
            rows[level].access = access
        else:
            db.add(MemberLevelAccess(organization_id=ctx.org_id, user_id=user_id, level=level, access=access))

    # Grupo: se lo saca del que le daba el puesto anterior (no de los que lo
    # sumaron a mano) y se lo suma al del nuevo.
    groups_removed, groups_added = [], []
    if old and old.group and old.group != position.group and old.group in memberships:
        await db.delete(memberships[old.group])
        groups_removed.append(old.group)
    if position.group and position.group not in memberships:
        group = await _group_by_name(db, ctx.org_id, position.group)
        db.add(InternalGroupMember(group_id=group.id, organization_id=ctx.org_id, user_id=user_id))
        groups_added.append(position.group)
    return {
        "from": before,
        "to": {"position": position.id, "role": new_role, "levels": after_levels},
        "groups_added": groups_added,
        "groups_removed": groups_removed,
        "by": ctx.user.email,
    }


async def _memberships(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, InternalGroupMember]:
    return {
        group.name: row
        for row, group in (
            await db.execute(
                select(InternalGroupMember, InternalGroup)
                .join(InternalGroup, InternalGroup.id == InternalGroupMember.group_id)
                .where(InternalGroupMember.organization_id == org_id, InternalGroupMember.user_id == user_id)
            )
        ).all()
    }


def _gains(
    member_role: str, before_levels: dict[str, str], new: Position, after_levels: dict[str, str],
    group_names: set[str], old: Position | None,
) -> bool:
    """Si pasar a `new` le da a alguien más de lo que tiene."""
    new_role = "owner" if member_role == "owner" else new.role
    gains_rank = rank_of(new_role, after_levels.values()) > rank_of(member_role, before_levels.values())
    # Un admin ya ve todos los niveles: bajarse a uno no le da nada.
    gains_level = not is_admin_role(member_role) and any(
        ACCESS_ORDER[access] > ACCESS_ORDER.get(before_levels.get(level, ""), 0)
        for level, access in after_levels.items()
    )
    gains_group = new.group is not None and new.group not in group_names
    gains_watch = bool(set(new.watch_group_ids) - set(old.watch_group_ids if old else ()))
    return gains_rank or gains_level or gains_group or gains_watch


SELF_GAIN = "No podés darte más permisos vos: pedíselo a otra persona que administre la sede"


async def _levels_of(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    return dict(
        (
            await db.execute(
                select(MemberLevelAccess.level, MemberLevelAccess.access).where(
                    MemberLevelAccess.organization_id == org_id, MemberLevelAccess.user_id == user_id
                )
            )
        ).all()
    )


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError:  # otro pedido creó el grupo (o el puesto) a la vez
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Cambió a la vez desde otro lado: probá de nuevo") from None


@router.put("/users/{user_id}", response_model=OrgUserOut)
async def set_position(
    user_id: uuid.UUID,
    data: PositionIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Elige el puesto y los niveles de alguien de la sede, y lo traduce a permisos."""
    _require_user_manager(ctx)
    by_id = {p.id: p for p in await org_positions(db, ctx.org_id)}
    position = by_id.get(data.position)
    if position is None or any(level not in LEVELS for level in data.levels):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Puesto o nivel desconocido")
    chosen = [level for level in LEVELS if level in data.levels]
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.org_id, OrganizationMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa persona no es de esta sede")
    if member.role == "owner" and position.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Es quien creó la sede: sigue siendo Dirección de la sede")
    if not is_admin_role(position.role) and not chosen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elegí al menos un nivel")
    old = by_id.get(member.position or "")

    # Nadie se da más de lo que tiene: ni rango, ni un nivel con más acceso,
    # ni un grupo nuevo (que abre reuniones internas), ni grupos que mirar.
    if user_id == ctx.user.id:
        before_levels = await _levels_of(db, ctx.org_id, user_id)
        after_levels = {level: position.access for level in chosen}
        names = set(await _memberships(db, ctx.org_id, user_id))
        if _gains(member.role, before_levels, position, after_levels, names, old):
            raise HTTPException(status.HTTP_403_FORBIDDEN, SELF_GAIN)
    if is_admin_role(member.role) and not is_admin_role(position.role) and member.role != "owner":
        await _require_another_admin(db, ctx.org_id, member.id)

    detail = await _apply_position(db, ctx, member, position, chosen, old)
    await audit(db, ctx.org_id, ctx.user.id, "org.position_changed", "user", str(user_id), detail=detail)
    await _commit(db)
    return (await _org_users(db, ctx.org_id, only=user_id))[0]


# ── Puestos propios de la sede ───────────────────────────────────
#
# Además de los seis fijos, quien administra la sede arma los suyos ("Adviser",
# "Tutora"...). Cambiar los permisos de uno se aplica a toda la gente que lo
# tiene; borrarlo en uso pide a qué puesto pasarla.


class CustomPositionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    is_admin: bool = False
    access: Literal["total", "limitado"] = "limitado"
    group_id: uuid.UUID | None = None
    watch_group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


async def _check_custom(db: AsyncSession, org_id: uuid.UUID, data: CustomPositionIn, own_id: uuid.UUID | None) -> str:
    name = " ".join(data.name.split())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ponele un nombre al puesto")
    taken = {p.label.casefold() for p in await org_positions(db, org_id) if p.id != str(own_id)}
    if name.casefold() in taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay un puesto con ese nombre")
    wanted = {*data.watch_group_ids, *([data.group_id] if data.group_id else [])}
    if wanted:
        found = set(
            (
                await db.execute(
                    select(InternalGroup.id).where(InternalGroup.organization_id == org_id, InternalGroup.id.in_(wanted))
                )
            ).scalars()
        )
        if found != wanted:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ese grupo no es de esta sede")
    return name


async def _custom_row(db: AsyncSession, org_id: uuid.UUID, position_id: uuid.UUID) -> CustomPosition:
    row = (
        await db.execute(
            select(CustomPosition).where(CustomPosition.organization_id == org_id, CustomPosition.id == position_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese puesto no existe")
    return row


async def _holders(db: AsyncSession, org_id: uuid.UUID, position_id: str) -> list[OrganizationMember]:
    return list(
        (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id, OrganizationMember.position == position_id
                )
            )
        ).scalars()
    )


async def _move_holders(
    db: AsyncSession, ctx: OrgContext, holders: list[OrganizationMember], new: Position, old: Position
) -> list[dict]:
    """Les aplica `new` a todos, con los niveles que ya tenían cada uno."""
    if any(member.role == "owner" for member in holders) and not is_admin_role(new.role):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Lo tiene quien creó la sede: ese puesto tiene que administrar la sede"
        )
    if not is_admin_role(new.role) and any(is_admin_role(member.role) for member in holders):
        others = (
            await db.execute(
                select(func.count()).select_from(OrganizationMember).where(
                    OrganizationMember.organization_id == ctx.org_id,
                    OrganizationMember.id.not_in([member.id for member in holders]),
                    OrganizationMember.role.in_(("admin", "owner")),
                )
            )
        ).scalar()
        if not others:
            raise HTTPException(status.HTTP_409_CONFLICT, "La sede se quedaría sin nadie que la administre")
    details = []
    for member in holders:
        before_levels = await _levels_of(db, ctx.org_id, member.user_id)
        chosen = [level for level in LEVELS if level in before_levels]
        if member.user_id == ctx.user.id:
            names = set(await _memberships(db, ctx.org_id, member.user_id))
            after_levels = {level: new.access for level in chosen}
            if _gains(member.role, before_levels, new, after_levels, names, old):
                raise HTTPException(status.HTTP_403_FORBIDDEN, SELF_GAIN)
        details.append(await _apply_position(db, ctx, member, new, chosen, old))
    return details


@router.post("/positions", response_model=PositionOut, status_code=201)
async def create_position(
    data: CustomPositionIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    _require_user_manager(ctx)
    name = await _check_custom(db, ctx.org_id, data, None)
    row = CustomPosition(
        organization_id=ctx.org_id, name=name, description=data.description.strip(), is_admin=data.is_admin,
        access=data.access, group_id=data.group_id, watch_group_ids=list(dict.fromkeys(data.watch_group_ids)),
    )
    db.add(row)
    await db.flush()
    await audit(
        db, ctx.org_id, ctx.user.id, "org.position_created", "position", str(row.id),
        detail={**data.model_dump(mode="json"), "name": name, "by": ctx.user.email},
    )
    await _commit(db)
    return next(p for p in await _positions_out(db, ctx.org_id) if p.id == str(row.id))


@router.put("/positions/{position_id}", response_model=PositionOut)
async def update_position(
    position_id: uuid.UUID,
    data: CustomPositionIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Cambia el puesto y se lo aplica a toda la gente que lo tiene."""
    _require_user_manager(ctx)
    row = await _custom_row(db, ctx.org_id, position_id)
    name = await _check_custom(db, ctx.org_id, data, position_id)
    old_group = None
    if row.group_id:
        old_group = (await db.execute(select(InternalGroup.name).where(InternalGroup.id == row.group_id))).scalar()
    old = custom_position(row, old_group)
    row.name, row.description, row.is_admin = name, data.description.strip(), data.is_admin
    row.access, row.group_id = data.access, data.group_id
    row.watch_group_ids = list(dict.fromkeys(data.watch_group_ids))
    new_group = None
    if row.group_id:
        new_group = (await db.execute(select(InternalGroup.name).where(InternalGroup.id == row.group_id))).scalar()
    new = custom_position(row, new_group)
    details = await _move_holders(db, ctx, await _holders(db, ctx.org_id, str(row.id)), new, old)
    await audit(
        db, ctx.org_id, ctx.user.id, "org.position_updated", "position", str(row.id),
        detail={**data.model_dump(mode="json"), "name": name, "applied_to": details, "by": ctx.user.email},
    )
    await _commit(db)
    return next(p for p in await _positions_out(db, ctx.org_id) if p.id == str(row.id))


@router.delete("/positions/{position_id}", status_code=204)
async def delete_position(
    position_id: uuid.UUID,
    move_to: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Borra un puesto propio. Si alguien lo tiene, `move_to` dice a qué puesto pasarlo."""
    _require_user_manager(ctx)
    row = await _custom_row(db, ctx.org_id, position_id)
    by_id = {p.id: p for p in await org_positions(db, ctx.org_id)}
    old = by_id[str(row.id)]
    holders = await _holders(db, ctx.org_id, str(row.id))
    details: list[dict] = []
    if holders:
        new = by_id.get(move_to or "")
        if new is None or new.id == old.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Hay gente con ese puesto: elegí a qué puesto pasarla")
        details = await _move_holders(db, ctx, holders, new, old)
    await db.delete(row)
    await audit(
        db, ctx.org_id, ctx.user.id, "org.position_deleted", "position", str(row.id),
        detail={"name": row.name, "moved_to": move_to, "applied_to": details, "by": ctx.user.email},
    )
    await _commit(db)


# ── Diccionario personalizado ────────────────────────────────────


class DictEntryIn(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="term")
    note: str | None = Field(default=None, max_length=300)


class DictEntryOut(DictEntryIn):
    id: uuid.UUID

    class Config:
        from_attributes = True


@router.get("/dictionary", response_model=list[DictEntryOut])
async def list_dictionary(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(OrgDictionaryEntry)
                .where(OrgDictionaryEntry.organization_id == ctx.org_id)
                .order_by(OrgDictionaryEntry.term)
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.post("/dictionary", response_model=DictEntryOut, status_code=201)
async def add_dictionary_entry(
    data: DictEntryIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("member")
    entry = OrgDictionaryEntry(
        organization_id=ctx.org_id, term=data.term.strip(), kind=data.kind, note=data.note
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "El término ya existe")
    await db.refresh(entry)
    return entry


@router.delete("/dictionary/{entry_id}", status_code=204)
async def delete_dictionary_entry(
    entry_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    await db.execute(
        delete(OrgDictionaryEntry).where(
            OrgDictionaryEntry.id == entry_id,
            OrgDictionaryEntry.organization_id == ctx.org_id,
        )
    )
    await db.commit()
