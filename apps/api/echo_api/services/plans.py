"""Qué hace la IA en cada reunión según el plan, los créditos y los topes.

Reglas (docs/plan-transcripcion-y-planes.md, §5), en este orden:

1. Organización con plan que siempre separa personas (Instituciones, o
   Cortesía para Northfield): la pasada final va siempre a ElevenLabs.
2. Persona con plan individual (US$ 5 / US$ 10): siempre, hasta las horas
   del mes que incluye su plan (`people_hours_per_month`).
3. Plan Base: la persona elige al crear la reunión si quiere "quién habló";
   si lo pide, gasta créditos (`credits_per_month` por mes y por persona; una
   reunión de más de 1 h gasta 2). Se renuevan cada mes, no se acumulan.

Por encima de todo: **una reunión donde hablan menores de 18 nunca va a
ElevenLabs** (su política lo prohíbe, §4). Va a Groq, sin personas.

Los topes salen de la base (BillingPlan.limits), pisados por los de la
organización y después por los de la persona: los pone un superadmin, no hay
números fijos acá. El "mes" es el calendario de Argentina (UTC-3).
"""
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import BillingPlan, Meeting, Organization, UsageEvent, User
from ..models.billing import PLAN_BASE

ARGENTINA = timezone(timedelta(hours=-3))

# Precios de los proveedores, en dólares (30/9/2026). Son costos nuestros, no
# topes: sirven para el panel de consumo.
PRICE_PER_HOUR = {
    ("groq", "whisper-large-v3-turbo"): 0.04,
    ("groq", "whisper-large-v3"): 0.111,
    ("elevenlabs", "scribe_v2"): 0.22,
    ("openai", "gpt-4o-transcribe"): 0.36,
    ("openai", "gpt-4o-transcribe-diarize"): 0.36,
    ("openai", "gpt-4o-mini-transcribe"): 0.18,
    ("openai", "whisper-1"): 0.36,
}
# Extras de Scribe por hora: diccionario (keyterms) y detección de entidades.
SCRIBE_KEYTERMS_PER_HOUR = 0.05
SCRIBE_ENTITIES_PER_HOUR = 0.07
# Groq cobra como mínimo 10 s por pedido (un tramo en vivo de 4 s paga 10).
GROQ_MIN_BILLED_SECONDS = 10


# LLM: dólares por millón de tokens (entrada, salida). Solo los precios
# confirmados; un modelo que no está acá se anota con sus tokens y sin costo
# ("precio desconocido" en el panel) en vez de inventar un número.
LLM_PRICE_PER_MTOK = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def llm_cost(model: str | None, tokens_in: int, tokens_out: int) -> float | None:
    price = LLM_PRICE_PER_MTOK.get(model or "")
    if price is None:
        return None
    return round((tokens_in * price[0] + tokens_out * price[1]) / 1_000_000, 6)


def month_start(now: datetime | None = None) -> datetime:
    """Primer instante del mes calendario en Argentina, en UTC."""
    local = (now or datetime.now(UTC)).astimezone(ARGENTINA)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def credits_for(duration_seconds: float) -> int:
    """Una reunión es 1 crédito; cada hora empezada después de la primera, 1 más."""
    return max(1, math.ceil(max(0.0, duration_seconds) / 3600))


def stt_cost(provider: str, model: str | None, seconds: float, keyterms: bool = False, entities: bool = False) -> float:
    per_hour = PRICE_PER_HOUR.get((provider, model or ""), 0.0)
    if provider == "elevenlabs":
        per_hour += (SCRIBE_KEYTERMS_PER_HOUR if keyterms else 0) + (SCRIBE_ENTITIES_PER_HOUR if entities else 0)
    if provider == "groq":
        seconds = max(seconds, GROQ_MIN_BILLED_SECONDS)
    return round(per_hour * seconds / 3600, 6)


async def plans_by_code(db: AsyncSession) -> dict[str, BillingPlan]:
    return {plan.code: plan for plan in (await db.execute(select(BillingPlan))).scalars().all()}


def _limits(*layers: dict | None) -> dict:
    """Topes de varias capas: cada una pisa a la anterior.

    Un valor vacío (None) en una capa no pisa nada: una organización o persona
    sin un tope propio usa el del plan, nunca queda "sin tope" por accidente.
    """
    out: dict = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if value is not None:
                out[key] = value
    return out


@dataclass
class MonthUsage:
    credits: int = 0
    people_seconds: float = 0.0  # de reuniones con personas cubiertas por el plan individual
    voice_seconds: float = 0.0
    audio_seconds: float = 0.0


async def month_usage(db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> MonthUsage:
    """Lo que esta persona gastó en el mes, en todas sus organizaciones."""
    rows = (
        await db.execute(
            select(
                UsageEvent.kind,
                func.coalesce(func.sum(UsageEvent.credits), 0),
                func.coalesce(func.sum(UsageEvent.quantity), 0.0),
                func.coalesce(
                    func.sum(UsageEvent.quantity).filter(UsageEvent.meta["covered_by"].astext == "individual"),
                    0.0,
                ),
            )
            .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= month_start(now))
            .group_by(UsageEvent.kind)
        )
    ).all()
    usage = MonthUsage()
    for kind, credits, quantity, individual in rows:
        usage.credits += int(credits)
        if kind == "voice":
            usage.voice_seconds += float(quantity)
        elif kind == "stt_final":
            usage.people_seconds += float(individual)
        if kind == "stt_live":
            usage.audio_seconds += float(quantity)
    return usage


def day_start(now: datetime | None = None) -> datetime:
    """Primer instante del día en Argentina, en UTC."""
    local = (now or datetime.now(UTC)).astimezone(ARGENTINA)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def abuse_limit(db: AsyncSession, org: Organization, user: User, key: str) -> float | None:
    """Un tope contra abuso (reuniones por día, horas de audio por mes). None = sin tope.

    De los dos planes (el de la organización y el de la persona) vale el más
    generoso; los topes propios de la organización y de la persona pisan eso.
    """
    if user.is_superadmin:
        return None
    by_code = await plans_by_code(db)
    layers = [plan.limits or {} for plan in (by_code.get(org.plan), by_code.get(user.plan)) if plan is not None]
    values = [layer.get(key) for layer in layers]
    from_plans = None if not values or any(value is None for value in values) else max(values)
    own = _limits(org.limits, user.limits)
    value = own.get(key, from_plans)
    return None if value is None else float(value)


async def check_meetings_today(db: AsyncSession, org: Organization, user: User) -> None:
    """Corta si la persona ya creó las reuniones que le permite el día."""
    cap = await abuse_limit(db, org, user, "meetings_per_day")
    if cap is None:
        return
    created = (
        await db.execute(
            select(func.count()).where(Meeting.created_by == user.id, Meeting.created_at >= day_start())
        )
    ).scalar_one()
    if created >= cap:
        raise LimitReached(f"Llegaste al tope de {int(cap)} reuniones por día. Mañana podés crear más.")


async def check_audio_month(db: AsyncSession, org: Organization, user: User) -> None:
    """Corta si la persona ya transcribió las horas de audio del mes."""
    cap = await abuse_limit(db, org, user, "audio_hours_per_month")
    if cap is None:
        return
    if (await month_usage(db, user.id)).audio_seconds >= cap * 3600:
        hours = "la hora" if cap == 1 else f"las {cap:g} horas"
        raise LimitReached(f"Ya usaste {hours} de audio de este mes. Se renuevan el 1°.")


class LimitReached(Exception):
    """Se llegó a un tope del plan; el mensaje es para la persona."""


@dataclass
class PeopleAccess:
    """Si las reuniones de esta persona en esta organización separan personas."""

    # always: siempre (plan de la organización o individual)
    # credits: si la persona lo pide, gastando créditos
    # none: no le quedan créditos
    mode: str
    # organization | individual | credits
    source: str
    org_plan: str
    user_plan: str
    credits_per_month: int | None
    credits_used: int
    credits_left: int | None
    people_hours_left: float | None


async def people_access(
    db: AsyncSession, org: Organization, user: User, now: datetime | None = None
) -> PeopleAccess:
    plans = await plans_by_code(db)
    org_plan = plans.get(org.plan) or plans.get(PLAN_BASE)
    user_plan = plans.get(user.plan) or plans.get(PLAN_BASE)
    usage = await month_usage(db, user.id, now)
    base_limits = plans[PLAN_BASE].limits if PLAN_BASE in plans else {}

    def result(mode: str, source: str, credits_per_month=None, credits_left=None, hours_left=None) -> PeopleAccess:
        return PeopleAccess(
            mode=mode,
            source=source,
            org_plan=org.plan,
            user_plan=user.plan,
            credits_per_month=credits_per_month,
            credits_used=usage.credits,
            credits_left=credits_left,
            people_hours_left=hours_left,
        )

    # Las cuentas de Becode (superadmins) tienen todo habilitado, en cualquier sede.
    if user.is_superadmin:
        return result("always", "organization")
    if org_plan is not None and org_plan.code != PLAN_BASE and (org_plan.features or {}).get("people") == "always":
        return result("always", "organization")

    if user_plan is not None and user_plan.code != PLAN_BASE and (user_plan.features or {}).get("people") == "always":
        limits = _limits(user_plan.limits, user.limits)
        hours = limits.get("people_hours_per_month")
        if hours is None:
            return result("always", "individual")
        left = max(0.0, float(hours) - usage.people_seconds / 3600)
        if left > 0:
            return result("always", "individual", hours_left=round(left, 2))
        # Se le terminaron las horas del plan: sigue como Base, con créditos.

    limits = _limits(base_limits, org.limits, user.limits)
    per_month = limits.get("credits_per_month")
    if per_month is None:
        return result("credits", "credits")
    left = max(0, int(per_month) - usage.credits)
    return result("credits" if left > 0 else "none", "credits", int(per_month), left)


@dataclass
class FinalPass:
    """Cómo se hace la pasada final de una reunión."""

    # elevenlabs: texto + quién habló | groq: solo texto
    provider: str
    credits: int = 0
    # organization | individual | credits (quién lo cubre, para el consumo)
    covered_by: str | None = None
    # Por qué no hay personas, para mostrarlo: minors | not_requested | no_credits | no_provider
    reason: str | None = None


def minors_present(meeting: Meeting) -> bool:
    return bool((meeting.meta or {}).get("minors"))


def people_requested(meeting: Meeting) -> bool:
    return bool((meeting.meta or {}).get("people"))


async def final_pass_for(db: AsyncSession, meeting: Meeting, duration_seconds: float) -> FinalPass:
    """Decide ElevenLabs o Groq para la pasada final de esta reunión."""
    if minors_present(meeting):
        return FinalPass("groq", reason="minors")
    if not get_settings().elevenlabs_api_key:
        return FinalPass("groq", reason="no_provider")
    org = await db.get(Organization, meeting.organization_id)
    user = await db.get(User, meeting.created_by)
    if org is None or user is None:
        return FinalPass("groq", reason="no_provider")
    access = await people_access(db, org, user)
    if access.mode == "always":
        return FinalPass("elevenlabs", covered_by=access.source)
    if not people_requested(meeting):
        return FinalPass("groq", reason="not_requested")
    if access.mode == "none":
        return FinalPass("groq", reason="no_credits")
    needed = credits_for(duration_seconds)
    # Si le queda menos de lo que cuesta, gasta lo que le queda: se le dijo
    # "gasta un crédito" al crearla y no se le saca la separación a mitad.
    charge = needed if access.credits_left is None else min(needed, access.credits_left)
    return FinalPass("elevenlabs", credits=charge, covered_by="credits")


async def record_usage(
    db: AsyncSession,
    *,
    kind: str,
    provider: str,
    model: str | None,
    unit: str,
    quantity: float,
    cost_usd: float,
    organization_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    meeting_id: uuid.UUID | None = None,
    credits: int = 0,
    meta: dict | None = None,
) -> UsageEvent:
    """Anota un consumo. No hace commit: lo hace quien llama."""
    event = UsageEvent(
        kind=kind,
        provider=provider,
        model=model,
        unit=unit,
        quantity=float(quantity),
        cost_usd=cost_usd,
        organization_id=organization_id,
        user_id=user_id,
        meeting_id=meeting_id,
        credits=credits,
        meta=meta,
    )
    db.add(event)
    return event
