"""Planes, créditos, pedidos de plan y consumo, vistos por cada persona.

- GET /api/billing/me: el plan de la organización y el propio, los créditos
  del mes y qué va a hacer la IA en una reunión nueva (lo muestra "Nueva
  reunión" y la página de planes).
- POST /api/billing/requests: "Suscribirme" / "Contact sales". Todavía no se
  cobra (no hay links de pago): queda el pedido y se avisa a Becode por una
  notificación a los superadmins y un mail a SALES_EMAIL, que nunca se
  muestra en la web.
- GET /api/billing/usage: consumo del mes (propio, o de cada miembro para los
  admins de la organización).
"""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import BillingPlan, Notification, OrganizationMember, PlanRequest, UsageEvent, User
from ..models.billing import PLAN_COURTESY, PLAN_INSTITUTION
from ..services import plans
from ..services.ai_settings import resolve_embeddings, resolve_llm
from ..services.audit import audit
from ..services.background import spawn
from ..services.mailer import send_mail

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Planes que se pueden pedir desde la web. Cortesía no: la asigna Becode.
REQUESTABLE = {"individual", "individual_voz", PLAN_INSTITUTION}
# Un pedido abierto del mismo plan no se repite en este plazo.
REQUEST_COOLDOWN = timedelta(days=7)


class PeopleOut(BaseModel):
    mode: str
    source: str
    credits_per_month: int | None
    credits_used: int
    credits_left: int | None
    people_hours_left: float | None
    available: bool


class FeaturesOut(BaseModel):
    transcription: bool
    minutes: bool
    tasks: bool
    chat: bool
    voice: bool


class PublicPlanOut(BaseModel):
    code: str
    name: str
    scope: str
    price_usd: float | None
    features: dict
    limits: dict


class RequestOut(BaseModel):
    id: uuid.UUID
    plan: str
    status: str
    created_at: datetime


class BillingOut(BaseModel):
    org_plan: str
    user_plan: str
    is_personal: bool
    people: PeopleOut
    features: FeaturesOut
    plans: list[PublicPlanOut]
    requests: list[RequestOut]
    month_start: datetime
    # Para "se renuevan el 1°": el primer instante del mes que viene.
    renews_at: datetime


def _next_month(start: datetime) -> datetime:
    local = start.astimezone(plans.ARGENTINA)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.replace(year=year, month=month).astimezone(UTC)


@router.get("/me", response_model=BillingOut)
async def my_billing(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    access = await plans.people_access(db, ctx.org, ctx.user)
    user_plan = (await db.execute(select(BillingPlan).where(BillingPlan.code == ctx.user.plan))).scalar_one_or_none()
    llm = await resolve_llm(db, ctx.org_id)
    embeddings = await resolve_embeddings(db, ctx.org_id)
    public = (
        (await db.execute(select(BillingPlan).where(BillingPlan.code != PLAN_COURTESY).order_by(BillingPlan.sort)))
        .scalars()
        .all()
    )
    requests = (
        (
            await db.execute(
                select(PlanRequest)
                .where(PlanRequest.user_id == ctx.user.id)
                .order_by(PlanRequest.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    start = plans.month_start()
    return BillingOut(
        org_plan=ctx.org.plan,
        user_plan=ctx.user.plan,
        is_personal=ctx.org.is_personal,
        people=PeopleOut(
            mode=access.mode,
            source=access.source,
            credits_per_month=access.credits_per_month,
            credits_used=access.credits_used,
            credits_left=access.credits_left,
            people_hours_left=access.people_hours_left,
            available=bool(get_settings().elevenlabs_api_key),
        ),
        features=FeaturesOut(
            transcription=True,
            minutes=llm is not None,
            tasks=llm is not None,
            chat=llm is not None and embeddings is not None,
            voice=ctx.user.is_superadmin or bool(user_plan and (user_plan.features or {}).get("voice")),
        ),
        plans=[
            PublicPlanOut(
                code=plan.code,
                name=plan.name,
                scope=plan.scope,
                # Instituciones: sin precio en la web, solo "Contact sales".
                price_usd=None if plan.code == PLAN_INSTITUTION or plan.price_usd is None else float(plan.price_usd),
                features=plan.features or {},
                limits=plan.limits or {},
            )
            for plan in public
        ],
        requests=[RequestOut(id=r.id, plan=r.plan, status=r.status, created_at=r.created_at) for r in requests],
        month_start=start,
        renews_at=_next_month(start),
    )


class PlanRequestIn(BaseModel):
    plan: str
    message: str | None = Field(default=None, max_length=1000)


@router.post("/requests", response_model=RequestOut, status_code=201)
async def request_plan(
    data: PlanRequestIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    if data.plan not in REQUESTABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ese plan no se puede pedir desde acá")
    # De a un pedido por persona: un doble clic no crea dos.
    await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx.user.id.int % (2**63 - 1)})
    recent = (
        await db.execute(
            select(PlanRequest)
            .where(
                PlanRequest.user_id == ctx.user.id,
                PlanRequest.plan == data.plan,
                PlanRequest.status == "new",
                PlanRequest.created_at > datetime.now(UTC) - REQUEST_COOLDOWN,
            )
            .order_by(PlanRequest.created_at.desc())
        )
    ).scalars().first()
    if recent is not None:
        return RequestOut(id=recent.id, plan=recent.plan, status=recent.status, created_at=recent.created_at)

    request = PlanRequest(
        user_id=ctx.user.id,
        organization_id=ctx.org_id,
        plan=data.plan,
        message=(data.message or "").strip() or None,
    )
    db.add(request)
    plan = (await db.execute(select(BillingPlan).where(BillingPlan.code == data.plan))).scalar_one_or_none()
    plan_name = plan.name if plan else data.plan
    title = f"{ctx.user.name} pidió el plan {plan_name}"
    body = f"{ctx.user.email} · {ctx.org.name}" + (f"\n\n{request.message}" if request.message else "")
    admins = (await db.execute(select(User.id).where(User.is_superadmin.is_(True)))).scalars().all()
    for admin_id in admins:
        db.add(
            Notification(
                user_id=admin_id, organization_id=ctx.org_id, kind="plan_request", title=title[:300],
                body=body, link="/admin#pedidos",
            )
        )
    await audit(db, ctx.org_id, ctx.user.id, "billing.plan_request", "plan_request", data.plan)
    await db.commit()
    await db.refresh(request)
    spawn(
        send_mail(
            get_settings().sales_email,
            f"[Echo] {title}",
            f"{title}.\n\nPersona: {ctx.user.name} <{ctx.user.email}>\nOrganización: {ctx.org.name}"
            f"{' (cuenta individual)' if ctx.org.is_personal else ''}\nPlan: {plan_name}\n"
            f"Fecha: {request.created_at:%d/%m/%Y %H:%M} UTC\n"
            + (f"\nMensaje:\n{request.message}\n" if request.message else "")
            + "\nTodavía no hay cobro automático: contactala para darle de alta el plan desde el panel.",
        ),
        name=f"plan-request:{request.id}",
    )
    return RequestOut(id=request.id, plan=request.plan, status=request.status, created_at=request.created_at)


# ── Consumo ──────────────────────────────────────────────────────


def month_range(month: str | None) -> tuple[datetime, datetime]:
    """"2026-09" → [1/9, 1/10) de Argentina, en UTC. Sin mes: el actual."""
    if month:
        try:
            year, number = (int(part) for part in month.split("-", 1))
            start = datetime(year, number, 1, tzinfo=plans.ARGENTINA).astimezone(UTC)
        except (ValueError, TypeError) as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mes inválido (AAAA-MM)") from error
    else:
        start = plans.month_start()
    return start, _next_month(start)


class UsageLine(BaseModel):
    kind: str
    provider: str
    model: str | None
    unit: str
    quantity: float
    cost_usd: float
    credits: int
    events: int
    price_unknown: bool = False


class PersonUsage(BaseModel):
    user_id: uuid.UUID | None
    name: str
    email: str | None
    plan: str | None
    cost_usd: float
    credits: int
    audio_seconds: float
    tokens: float
    lines: list[UsageLine]


class UsageOut(BaseModel):
    month: str
    scope: str
    total_cost_usd: float
    total_credits: int
    people: list[PersonUsage]


async def usage_by_person(db: AsyncSession, start: datetime, end: datetime, *conditions) -> list[PersonUsage]:
    rows = (
        await db.execute(
            select(
                UsageEvent.user_id,
                UsageEvent.kind,
                UsageEvent.provider,
                UsageEvent.model,
                UsageEvent.unit,
                func.sum(UsageEvent.quantity),
                func.sum(UsageEvent.cost_usd),
                func.sum(UsageEvent.credits),
                func.count(),
                func.bool_or(UsageEvent.meta["price_unknown"].astext == "true"),
            )
            .where(UsageEvent.created_at >= start, UsageEvent.created_at < end, *conditions)
            .group_by(UsageEvent.user_id, UsageEvent.kind, UsageEvent.provider, UsageEvent.model, UsageEvent.unit)
        )
    ).all()
    user_ids = {row[0] for row in rows if row[0] is not None}
    users = {
        user.id: user
        for user in (await db.execute(select(User).where(User.id.in_(user_ids or [uuid.uuid4()])))).scalars()
    }
    people: dict[uuid.UUID | None, PersonUsage] = {}
    for user_id, kind, provider, model, unit, quantity, cost, credits, events, unknown in rows:
        user = users.get(user_id)
        person = people.setdefault(
            user_id,
            PersonUsage(
                user_id=user_id,
                name=user.name if user else "Sin persona",
                email=user.email if user else None,
                plan=user.plan if user else None,
                cost_usd=0.0, credits=0, audio_seconds=0.0, tokens=0.0, lines=[],
            ),
        )
        line = UsageLine(
            kind=kind, provider=provider, model=model, unit=unit, quantity=float(quantity or 0),
            cost_usd=float(cost or 0), credits=int(credits or 0), events=int(events), price_unknown=bool(unknown),
        )
        person.lines.append(line)
        person.cost_usd += line.cost_usd
        person.credits += line.credits
        if unit == "audio_seconds":
            person.audio_seconds += line.quantity
        elif unit == "tokens":
            person.tokens += line.quantity
    out = sorted(people.values(), key=lambda person: person.cost_usd, reverse=True)
    for person in out:
        person.cost_usd = round(person.cost_usd, 4)
        person.lines.sort(key=lambda line: line.cost_usd, reverse=True)
    return out


@router.get("/usage", response_model=UsageOut)
async def usage(
    month: str | None = Query(default=None, max_length=7),
    scope: str = Query(default="me", pattern="^(me|org)$"),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    start, end = month_range(month)
    if scope == "org":
        ctx.require_role("admin")
        people = await usage_by_person(db, start, end, UsageEvent.organization_id == ctx.org_id)
        # Los miembros que no gastaron nada también aparecen, en cero.
        members = (
            await db.execute(
                select(User)
                .join(OrganizationMember, OrganizationMember.user_id == User.id)
                .where(OrganizationMember.organization_id == ctx.org_id, User.deleted_at.is_(None))
            )
        ).scalars().all()
        seen = {person.user_id for person in people}
        people += [
            PersonUsage(user_id=m.id, name=m.name, email=m.email, plan=m.plan, cost_usd=0, credits=0,
                        audio_seconds=0, tokens=0, lines=[])
            for m in members if m.id not in seen
        ]
    else:
        people = await usage_by_person(db, start, end, UsageEvent.user_id == ctx.user.id)
        if not people:
            people = [PersonUsage(user_id=ctx.user.id, name=ctx.user.name, email=ctx.user.email, plan=ctx.user.plan,
                                  cost_usd=0, credits=0, audio_seconds=0, tokens=0, lines=[])]
    local = start.astimezone(plans.ARGENTINA)
    return UsageOut(
        month=f"{local.year:04d}-{local.month:02d}",
        scope=scope,
        total_cost_usd=round(sum(person.cost_usd for person in people), 4),
        total_credits=sum(person.credits for person in people),
        people=people,
    )
