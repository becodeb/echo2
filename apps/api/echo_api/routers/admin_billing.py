"""Panel de superadmin: planes, topes y quién tiene qué plan.

Los topes contra abuso no están en el código: se ajustan acá por plan, por
organización o por persona (services/plans.py). Una organización con plan
"cortesia" (Northfield) tiene todo habilitado sin pagar.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ORG_PLANS, USER_PLANS, BillingPlan, Organization, User
from ..models.billing import FEATURE_KEYS, LIMIT_KEYS
from ..services.audit import audit
from .admin import get_superadmin

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_limits(limits: dict | None) -> dict | None:
    """Solo claves conocidas y números no negativos (None = sin tope)."""
    if limits is None:
        return None
    out: dict = {}
    for key, value in limits.items():
        if key not in LIMIT_KEYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Tope desconocido: {key}")
        if value is None:
            out[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"El tope {key} tiene que ser un número ≥ 0")
        out[key] = value
    return out


class PlanOut(BaseModel):
    code: str
    name: str
    scope: str
    price_usd: float | None
    features: dict
    limits: dict
    sort: int


class PlanIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    price_usd: float | None = Field(default=None, ge=0)
    features: dict | None = None
    limits: dict | None = None


def _plan_out(plan: BillingPlan) -> PlanOut:
    return PlanOut(
        code=plan.code,
        name=plan.name,
        scope=plan.scope,
        price_usd=float(plan.price_usd) if plan.price_usd is not None else None,
        features=plan.features or {},
        limits=plan.limits or {},
        sort=plan.sort,
    )


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(BillingPlan).order_by(BillingPlan.sort))).scalars().all()
    return [_plan_out(plan) for plan in plans]


@router.put("/plans/{code}", response_model=PlanOut)
async def update_plan(
    code: str, data: PlanIn, admin: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)
):
    plan = (await db.execute(select(BillingPlan).where(BillingPlan.code == code))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan no encontrado")
    if data.name is not None:
        plan.name = data.name.strip() or plan.name
    if "price_usd" in data.model_fields_set:
        plan.price_usd = data.price_usd
    if data.features is not None:
        unknown = set(data.features) - set(FEATURE_KEYS)
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Función desconocida: {', '.join(unknown)}")
        if data.features.get("people", "credits") not in ("always", "credits"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "people: always o credits")
        plan.features = {**(plan.features or {}), **data.features}
    if data.limits is not None:
        merged = {**(plan.limits or {}), **_check_limits(data.limits)}
        plan.limits = {key: value for key, value in merged.items() if value is not None}
    await audit(db, None, admin.id, "admin.plan_update", "billing_plan", code, detail={"by": admin.email})
    await db.commit()
    return _plan_out(plan)


class AssignPlanIn(BaseModel):
    plan: str | None = None
    # None = no tocar; {} = sin topes propios.
    limits: dict | None = None


class OrgPlanOut(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    is_personal: bool
    limits: dict


@router.put("/organizations/{org_id}/plan", response_model=OrgPlanOut)
async def set_organization_plan(
    org_id: uuid.UUID,
    data: AssignPlanIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, org_id)
    if not org or org.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")
    if data.plan is not None:
        if data.plan not in ORG_PLANS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Plan de organización desconocido")
        org.plan = data.plan
    if data.limits is not None:
        org.limits = _check_limits(data.limits) or None
    await audit(
        db, org_id, admin.id, "admin.org_plan", "organization", str(org_id),
        detail={"by": admin.email, "plan": org.plan, "limits": org.limits},
    )
    await db.commit()
    return OrgPlanOut(id=org.id, name=org.name, plan=org.plan, is_personal=org.is_personal, limits=org.limits or {})


class UserPlanOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    plan: str
    limits: dict


@router.get("/users", response_model=list[UserPlanOut])
async def search_users(
    q: str = Query(default="", max_length=120),
    _: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Personas por nombre o email (para asignarles un plan individual)."""
    query = select(User).where(User.deleted_at.is_(None))
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.email).like(pattern), func.lower(User.name).like(pattern)))
    users = (await db.execute(query.order_by(User.name).limit(50))).scalars().all()
    return [UserPlanOut(id=u.id, name=u.name, email=u.email, plan=u.plan, limits=u.limits or {}) for u in users]


@router.put("/users/{user_id}/plan", response_model=UserPlanOut)
async def set_user_plan(
    user_id: uuid.UUID,
    data: AssignPlanIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    if data.plan is not None:
        if data.plan not in USER_PLANS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Plan individual desconocido")
        user.plan = data.plan
    if data.limits is not None:
        user.limits = _check_limits(data.limits) or None
    await audit(
        db, None, admin.id, "admin.user_plan", "user", str(user_id),
        detail={"by": admin.email, "plan": user.plan, "limits": user.limits},
    )
    await db.commit()
    return UserPlanOut(id=user.id, name=user.name, email=user.email, plan=user.plan, limits=user.limits or {})
