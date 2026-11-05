"""Panel de superadmin: todos los usuarios de la instalación, de todas las sedes.

Acá solo se lista y se suma a alguien a una sede. Cambiar puesto, niveles o rol y
sacar de una sede pasa por /api/org/... con esa sede en el header, que deja entrar
al superadmin como owner: así valen las mismas reglas que en Ajustes (la sede no
se queda sin admin, quien la creó no se toca) y queda en el historial de la sede.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    LEVELS,
    CustomPosition,
    InternalGroup,
    InternalGroupMember,
    MemberLevelAccess,
    Organization,
    OrganizationMember,
    RefreshToken,
    User,
    UserVoiceSample,
)
from ..services.audit import audit
from ..services.positions import BY_ID, guess_position
from .admin import get_superadmin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class MembershipOut(BaseModel):
    member_id: uuid.UUID
    organization_id: uuid.UUID
    organization: str
    is_personal: bool
    role: str
    # El puesto elegido; si no, el que parece por sus permisos (`guessed`).
    position: str | None
    guessed: bool
    levels: dict[str, str]


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    avatar_color: str
    avatar_url: str | None
    plan: str
    is_superadmin: bool
    is_active: bool
    last_seen_at: datetime | None
    has_voice: bool
    memberships: list[MembershipOut]


@router.get("/people", response_model=list[PersonOut])
async def list_people(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    users = (
        (await db.execute(select(User).where(User.deleted_at.is_(None)).order_by(func.lower(User.name))))
        .scalars()
        .all()
    )
    levels: dict[tuple[uuid.UUID, uuid.UUID], dict[str, str]] = {}
    for row in (await db.execute(select(MemberLevelAccess))).scalars():
        levels.setdefault((row.user_id, row.organization_id), {})[row.level] = row.access
    groups: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = {}
    for user_id, org_id, name in (
        await db.execute(
            select(InternalGroupMember.user_id, InternalGroupMember.organization_id, InternalGroup.name).join(
                InternalGroup, InternalGroup.id == InternalGroupMember.group_id
            )
        )
    ).all():
        groups.setdefault((user_id, org_id), set()).add(name)
    custom = dict((await db.execute(select(CustomPosition.id, CustomPosition.name))).all())
    custom_labels = {str(position_id): name for position_id, name in custom.items()}

    def label(position_id: str | None) -> str | None:
        if position_id in BY_ID:
            return BY_ID[position_id].label
        return custom_labels.get(position_id or "")

    memberships: dict[uuid.UUID, list[MembershipOut]] = {}
    for member, org in (
        await db.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(Organization.deleted_at.is_(None))
            .order_by(Organization.name)
        )
    ).all():
        key = (member.user_id, org.id)
        own_levels = levels.get(key, {})
        chosen = label(member.position)
        memberships.setdefault(member.user_id, []).append(
            MembershipOut(
                member_id=member.id,
                organization_id=org.id,
                organization=org.name,
                is_personal=org.is_personal,
                role=member.role,
                position=chosen
                or label(guess_position(member.role, list(own_levels.values()), groups.get(key, set()))),
                guessed=chosen is None,
                levels={level: own_levels[level] for level in LEVELS if level in own_levels},
            )
        )
    last_seen = dict(
        (
            await db.execute(select(RefreshToken.user_id, func.max(RefreshToken.created_at)).group_by(RefreshToken.user_id))
        ).all()
    )
    voices = set((await db.execute(select(UserVoiceSample.user_id))).scalars())
    return [
        PersonOut(
            id=user.id,
            name=user.name,
            email=user.email,
            avatar_color=user.avatar_color,
            avatar_url=user.avatar_url,
            plan=user.plan,
            is_superadmin=user.is_superadmin,
            is_active=user.is_active,
            last_seen_at=last_seen.get(user.id),
            has_voice=user.id in voices,
            memberships=memberships.get(user.id, []),
        )
        for user in users
    ]


class AddMembershipIn(BaseModel):
    organization_id: uuid.UUID


@router.post("/people/{user_id}/memberships", status_code=201)
async def add_to_campus(
    user_id: uuid.UUID,
    data: AddMembershipIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Suma a alguien a una sede sin invitación. Entra como miembro, sin niveles."""
    user = await db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    org = await db.get(Organization, data.organization_id)
    if not org or org.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sede no encontrada")
    if org.is_personal:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Una cuenta individual es de una sola persona")
    existing = (
        await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == org.id, OrganizationMember.user_id == user_id
            )
        )
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya es de esa sede")
    member = OrganizationMember(organization_id=org.id, user_id=user_id, role="member")
    db.add(member)
    await db.flush()
    await audit(
        db, org.id, admin.id, "admin.member_added", "member", str(member.id),
        detail={"user_id": str(user_id), "email": user.email, "by": admin.email},
    )
    await db.commit()
    return {"member_id": str(member.id), "organization_id": str(org.id)}
