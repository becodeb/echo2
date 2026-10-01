"""Panel de superadmin: planes, topes y quién tiene qué plan.

Los topes contra abuso no están en el código: se ajustan acá por plan, por
organización o por persona (services/plans.py). Una organización con plan
"cortesia" (Northfield) tiene todo habilitado sin pagar.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ORG_PLANS, USER_PLANS, BillingPlan, Organization, PlanRequest, UsageEvent, User
from ..models.billing import FEATURE_KEYS, LIMIT_KEYS
from ..services.audit import audit
from ..services.plans import ARGENTINA
from .admin import get_superadmin
from .billing import PersonUsage, month_range, usage_by_person

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


def _own_limits(limits: dict) -> dict | None:
    """Topes propios de una organización o persona: lo vacío vuelve al del plan."""
    own = {key: value for key, value in (_check_limits(limits) or {}).items() if value is not None}
    return own or None


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
        org.limits = _own_limits(data.limits)
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
        user.limits = _own_limits(data.limits)
    await audit(
        db, None, admin.id, "admin.user_plan", "user", str(user_id),
        detail={"by": admin.email, "plan": user.plan, "limits": user.limits},
    )
    await db.commit()
    return UserPlanOut(id=user.id, name=user.name, email=user.email, plan=user.plan, limits=user.limits or {})


# ── Consumo de toda la instalación ───────────────────────────────


class OrgUsageOut(BaseModel):
    id: uuid.UUID | None
    name: str
    plan: str | None
    is_personal: bool
    cost_usd: float
    credits: int
    audio_seconds: float
    tokens: float
    people: list[PersonUsage]


class AdminUsageOut(BaseModel):
    month: str
    total_cost_usd: float
    total_credits: int
    organizations: list[OrgUsageOut]
    # Quienes pagan un plan individual, estén o no dentro de un colegio.
    individuals: list[PersonUsage]


@router.get("/usage", response_model=AdminUsageOut)
async def usage_everywhere(
    month: str | None = Query(default=None, max_length=7),
    _: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    start, end = month_range(month)
    org_rows = (
        await db.execute(
            select(UsageEvent.organization_id).where(UsageEvent.created_at >= start, UsageEvent.created_at < end)
            .group_by(UsageEvent.organization_id)
        )
    ).scalars().all()
    orgs = {
        org.id: org
        for org in (await db.execute(select(Organization).where(Organization.id.in_([o for o in org_rows if o] or [uuid.uuid4()])))).scalars()
    }
    out: list[OrgUsageOut] = []
    for org_id in org_rows:
        people = await usage_by_person(db, start, end, UsageEvent.organization_id == org_id)
        org = orgs.get(org_id)
        out.append(
            OrgUsageOut(
                id=org_id,
                name=org.name if org else "Sin organización",
                plan=org.plan if org else None,
                is_personal=bool(org and org.is_personal),
                cost_usd=round(sum(p.cost_usd for p in people), 4),
                credits=sum(p.credits for p in people),
                audio_seconds=sum(p.audio_seconds for p in people),
                tokens=sum(p.tokens for p in people),
                people=people,
            )
        )
    out.sort(key=lambda org: org.cost_usd, reverse=True)

    paying = (await db.execute(select(User.id).where(User.plan != "base", User.deleted_at.is_(None)))).scalars().all()
    individuals = await usage_by_person(db, start, end, UsageEvent.user_id.in_(paying or [uuid.uuid4()]))
    seen = {person.user_id for person in individuals}
    for user in (await db.execute(select(User).where(User.id.in_(paying or [uuid.uuid4()])))).scalars():
        if user.id not in seen:
            individuals.append(PersonUsage(user_id=user.id, name=user.name, email=user.email, plan=user.plan,
                                           cost_usd=0, credits=0, audio_seconds=0, tokens=0, lines=[]))
    local = start.astimezone(ARGENTINA)
    return AdminUsageOut(
        month=f"{local.year:04d}-{local.month:02d}",
        total_cost_usd=round(sum(org.cost_usd for org in out), 4),
        total_credits=sum(org.credits for org in out),
        organizations=out,
        individuals=individuals,
    )


# ── Pedidos de plan ──────────────────────────────────────────────


class PlanRequestAdminOut(BaseModel):
    id: uuid.UUID
    plan: str
    status: str
    message: str | None
    created_at: datetime
    user_id: uuid.UUID
    user_name: str
    user_email: str
    organization_id: uuid.UUID | None
    organization_name: str | None


class PlanRequestStatusIn(BaseModel):
    status: str = Field(pattern="^(new|contacted|done|cancelled)$")


@router.get("/plan-requests", response_model=list[PlanRequestAdminOut])
async def list_plan_requests(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(PlanRequest, User, Organization)
            .join(User, User.id == PlanRequest.user_id)
            .outerjoin(Organization, Organization.id == PlanRequest.organization_id)
            .order_by(PlanRequest.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        PlanRequestAdminOut(
            id=request.id, plan=request.plan, status=request.status, message=request.message,
            created_at=request.created_at, user_id=user.id, user_name=user.name, user_email=user.email,
            organization_id=org.id if org else None, organization_name=org.name if org else None,
        )
        for request, user, org in rows
    ]


@router.put("/plan-requests/{request_id}", response_model=PlanRequestAdminOut)
async def set_plan_request_status(
    request_id: uuid.UUID,
    data: PlanRequestStatusIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    request = await db.get(PlanRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    request.status = data.status
    await audit(db, request.organization_id, admin.id, "admin.plan_request", "plan_request", str(request_id),
                detail={"by": admin.email, "status": data.status})
    await db.commit()
    user = await db.get(User, request.user_id)
    org = await db.get(Organization, request.organization_id) if request.organization_id else None
    return PlanRequestAdminOut(
        id=request.id, plan=request.plan, status=request.status, message=request.message,
        created_at=request.created_at, user_id=user.id, user_name=user.name, user_email=user.email,
        organization_id=org.id if org else None, organization_name=org.name if org else None,
    )
