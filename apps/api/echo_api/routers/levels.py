"""Niveles de la sede y quién ve qué de cada uno.

- Cada persona dice de qué nivel es al entrar (queda con acceso "limitado":
  ve lo suyo). Nadie se da más acceso a sí mismo.
- Dirección de un nivel ve todo ese nivel y asigna total/limitado/nulo a
  quienes están en él. No puede nombrar ni sacar a otra dirección.
- Admins de la sede y superadmins ven todo y asignan cualquier acceso,
  incluida la dirección.

La regla de visibilidad que se deriva de esto está en services/access.py.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import LEVELS, MemberLevelAccess, OrganizationMember, User
from ..services.audit import audit

router = APIRouter(prefix="/api/org/access", tags=["levels"])

ACCESS_VALUES = ("direccion", "total", "limitado", "nulo")


class MyAccessOut(BaseModel):
    sees_everything: bool
    superadmin_visit: bool
    access: dict[str, str]
    creatable_levels: list[str]
    managed_levels: list[str]
    needs_level: bool


async def _my_access(ctx: OrgContext, db: AsyncSession) -> MyAccessOut:
    scope = await ctx.scope(db)
    return MyAccessOut(
        sees_everything=scope.sees_everything,
        superadmin_visit=ctx.superadmin_visit,
        access=scope.access,
        creatable_levels=scope.creatable_levels,
        managed_levels=[level for level in LEVELS if level in scope.managed_levels],
        needs_level=scope.needs_level,
    )


@router.get("/me", response_model=MyAccessOut)
async def my_access(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    return await _my_access(ctx, db)


class DeclareIn(BaseModel):
    levels: list[str] = Field(min_length=1, max_length=len(LEVELS))


@router.post("/me", response_model=MyAccessOut)
async def declare_levels(
    data: DeclareIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    """Quien recién entra dice de qué nivel es. Queda con acceso limitado."""
    scope = await ctx.scope(db)
    if not scope.needs_level:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tu nivel ya está asignado: lo cambia dirección")
    if any(level not in LEVELS for level in data.levels):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nivel desconocido")
    for level in dict.fromkeys(data.levels):
        db.add(MemberLevelAccess(organization_id=ctx.org_id, user_id=ctx.user.id, level=level, access="limitado"))
    await audit(db, ctx.org_id, ctx.user.id, "levels.declare", "user", str(ctx.user.id), detail={"levels": data.levels})
    await db.commit()
    ctx._scope = None
    return await _my_access(ctx, db)


class MemberAccessOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    access: dict[str, str]


class AccessListOut(BaseModel):
    managed_levels: list[str]
    can_assign_direction: bool
    members: list[MemberAccessOut]


@router.get("", response_model=AccessListOut)
async def list_access(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    scope = await ctx.scope(db)
    managed = [level for level in LEVELS if level in scope.managed_levels]
    if not managed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo dirección o un admin ve los accesos")
    members = (
        await db.execute(
            select(User, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == ctx.org_id)
            .order_by(User.name)
        )
    ).all()
    rows = (
        await db.execute(select(MemberLevelAccess).where(MemberLevelAccess.organization_id == ctx.org_id))
    ).scalars().all()
    by_user: dict[uuid.UUID, dict[str, str]] = {}
    for row in rows:
        # Dirección de un nivel ve solo las columnas de sus niveles.
        if row.level in managed:
            by_user.setdefault(row.user_id, {})[row.level] = row.access
    out = []
    for user, role in members:
        access = by_user.get(user.id, {})
        # A quien dirige solo un nivel se le listan las personas de ese nivel
        # (y las que todavía no eligieron ninguno), no toda la sede.
        if not scope.sees_everything and not access and user.id in {row.user_id for row in rows}:
            continue
        out.append(MemberAccessOut(user_id=user.id, name=user.name, email=user.email, role=role, access=access))
    return AccessListOut(managed_levels=managed, can_assign_direction=scope.sees_everything, members=out)


class SetAccessIn(BaseModel):
    user_id: uuid.UUID
    level: str
    access: str


@router.put("", response_model=MemberAccessOut)
async def set_access(
    data: SetAccessIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    if data.level not in LEVELS or data.access not in ACCESS_VALUES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nivel o acceso desconocido")
    scope = await ctx.scope(db)
    if data.level not in scope.managed_levels:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No dirigís ese nivel")

    target = (
        await db.execute(
            select(User, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == ctx.org_id, User.id == data.user_id)
        )
    ).first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa persona no es de esta sede")
    user, role = target
    if role in ("admin", "owner"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Es admin de la sede: ya ve todos los niveles")

    current = (
        await db.execute(
            select(MemberLevelAccess).where(
                MemberLevelAccess.organization_id == ctx.org_id,
                MemberLevelAccess.user_id == user.id,
                MemberLevelAccess.level == data.level,
            )
        )
    ).scalar_one_or_none()
    if not scope.sees_everything:
        if data.access == "direccion":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "La dirección la asigna un admin")
        if current is not None and current.access == "direccion":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No podés cambiar el acceso de otra dirección")
        if user.id == ctx.user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu propio acceso lo cambia un admin")

    if data.access == "nulo":
        await db.execute(
            delete(MemberLevelAccess).where(
                MemberLevelAccess.organization_id == ctx.org_id,
                MemberLevelAccess.user_id == user.id,
                MemberLevelAccess.level == data.level,
            )
        )
    elif current is None:
        db.add(MemberLevelAccess(organization_id=ctx.org_id, user_id=user.id, level=data.level, access=data.access))
    else:
        current.access = data.access
    await audit(
        db, ctx.org_id, ctx.user.id, "levels.set_access", "user", str(user.id),
        detail={"level": data.level, "access": data.access, "by": ctx.user.email},
    )
    await db.commit()

    rows = (
        await db.execute(
            select(MemberLevelAccess).where(
                MemberLevelAccess.organization_id == ctx.org_id, MemberLevelAccess.user_id == user.id
            )
        )
    ).scalars().all()
    managed = scope.managed_levels
    return MemberAccessOut(
        user_id=user.id, name=user.name, email=user.email, role=role,
        access={row.level: row.access for row in rows if row.level in managed},
    )
