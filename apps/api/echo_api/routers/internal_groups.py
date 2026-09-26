"""Grupos internos (Directivos, Coordinadores...) y quién es de cada uno.

Ser del grupo es lo que deja ver sus reuniones internas (services/access.py).
Los administra un admin/owner de la sede o dirección de algún nivel; sumar o
sacar a alguien queda en el log de auditoría, porque es darle acceso a
reuniones que antes no veía.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import DEFAULT_GROUPS, InternalGroup, InternalGroupMember, Meeting, OrganizationMember, User
from ..services.access import Scope
from ..services.audit import audit

router = APIRouter(prefix="/api/internal-groups", tags=["internal-groups"])


class GroupMemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    is_member: bool
    meetings: int
    members: list[GroupMemberOut]


class GroupsOut(BaseModel):
    can_manage: bool
    groups: list[GroupOut]


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def can_manage_groups(scope: Scope) -> bool:
    return scope.sees_everything or "direccion" in scope.access.values()


async def _ensure_defaults(db: AsyncSession, org_id: uuid.UUID) -> None:
    exists = (
        await db.execute(select(func.count()).select_from(InternalGroup).where(InternalGroup.organization_id == org_id))
    ).scalar()
    if exists:
        return
    for name in DEFAULT_GROUPS:
        db.add(InternalGroup(organization_id=org_id, name=name))
    try:
        await db.commit()
    except IntegrityError:  # otro pedido los creó a la vez
        await db.rollback()


async def _get_group(group_id: uuid.UUID, ctx: OrgContext, db: AsyncSession) -> InternalGroup:
    group = await db.get(InternalGroup, group_id)
    if group is None or group.organization_id != ctx.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo no encontrado")
    return group


async def _require_manager(ctx: OrgContext, db: AsyncSession) -> Scope:
    scope = await ctx.scope(db)
    if not can_manage_groups(scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo dirección o un admin administran los grupos")
    return scope


@router.get("", response_model=GroupsOut)
async def list_groups(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    await _ensure_defaults(db, ctx.org_id)
    scope = await ctx.scope(db)
    groups = (
        (await db.execute(select(InternalGroup).where(InternalGroup.organization_id == ctx.org_id).order_by(InternalGroup.name)))
        .scalars()
        .all()
    )
    ids = [group.id for group in groups]
    members: dict[uuid.UUID, list[GroupMemberOut]] = {}
    for row, user in (
        await db.execute(
            select(InternalGroupMember, User)
            .join(User, User.id == InternalGroupMember.user_id)
            .where(InternalGroupMember.group_id.in_(ids))
            .order_by(User.name)
        )
    ).all():
        members.setdefault(row.group_id, []).append(GroupMemberOut(user_id=user.id, name=user.name, email=user.email))
    counts = dict(
        (
            await db.execute(
                select(Meeting.group_id, func.count())
                .where(Meeting.group_id.in_(ids), Meeting.deleted_at.is_(None))
                .group_by(Meeting.group_id)
            )
        ).all()
    )
    return GroupsOut(
        can_manage=can_manage_groups(scope),
        groups=[
            GroupOut(
                id=group.id,
                name=group.name,
                is_member=group.id in scope.groups,
                meetings=counts.get(group.id, 0),
                members=members.get(group.id, []),
            )
            for group in groups
        ],
    )


@router.post("", response_model=GroupOut, status_code=201)
async def create_group(data: GroupIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    await _require_manager(ctx, db)
    group = InternalGroup(organization_id=ctx.org_id, name=data.name.strip())
    db.add(group)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay un grupo con ese nombre") from None
    await audit(db, ctx.org_id, ctx.user.id, "internal_group.create", "internal_group", str(group.id),
                detail={"name": group.name})
    await db.commit()
    return GroupOut(id=group.id, name=group.name, is_member=False, meetings=0, members=[])


@router.patch("/{group_id}", response_model=GroupOut)
async def rename_group(
    group_id: uuid.UUID, data: GroupIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    await _require_manager(ctx, db)
    group = await _get_group(group_id, ctx, db)
    previous = group.name
    group.name = data.name.strip()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay un grupo con ese nombre") from None
    await audit(db, ctx.org_id, ctx.user.id, "internal_group.rename", "internal_group", str(group.id),
                detail={"from": previous, "to": group.name})
    await db.commit()
    groups = await list_groups(ctx, db)
    return next(item for item in groups.groups if item.id == group.id)


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    await _require_manager(ctx, db)
    group = await _get_group(group_id, ctx, db)
    # Con reuniones adentro, borrarlo las dejaría sin nadie que las vea salvo
    # quien las creó: que primero se muevan o se borren.
    used = (
        await db.execute(
            select(func.count()).select_from(Meeting).where(Meeting.group_id == group.id, Meeting.deleted_at.is_(None))
        )
    ).scalar()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "El grupo tiene reuniones: no se puede borrar")
    await audit(db, ctx.org_id, ctx.user.id, "internal_group.delete", "internal_group", str(group.id),
                detail={"name": group.name})
    await db.delete(group)
    await db.commit()


@router.put("/{group_id}/members/{user_id}", status_code=204)
async def add_member(
    group_id: uuid.UUID, user_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    await _require_manager(ctx, db)
    group = await _get_group(group_id, ctx, db)
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.org_id, OrganizationMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa persona no es de la sede")
    existing = (
        await db.execute(
            select(InternalGroupMember).where(
                InternalGroupMember.group_id == group.id, InternalGroupMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(InternalGroupMember(group_id=group.id, organization_id=ctx.org_id, user_id=user_id))
    await audit(db, ctx.org_id, ctx.user.id, "internal_group.member_add", "internal_group", str(group.id),
                detail={"user_id": str(user_id), "group": group.name})
    await db.commit()


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    await _require_manager(ctx, db)
    group = await _get_group(group_id, ctx, db)
    row = (
        await db.execute(
            select(InternalGroupMember).where(
                InternalGroupMember.group_id == group.id, InternalGroupMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    await db.delete(row)
    await audit(db, ctx.org_id, ctx.user.id, "internal_group.member_remove", "internal_group", str(group.id),
                detail={"user_id": str(user_id), "group": group.name})
    await db.commit()
