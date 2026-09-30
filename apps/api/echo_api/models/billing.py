"""Planes, créditos y consumo (docs/plan-transcripcion-y-planes.md, §5).

- `BillingPlan`: qué incluye cada plan y sus topes. Los topes viven en la base
  y no en el código: los ajusta un superadmin desde el panel, por plan, y los
  puede pisar por organización (`organizations.limits`) o por persona
  (`users.limits`).
- El plan de una organización está en `organizations.plan`; el plan individual
  que paga una persona (aunque esté dentro de un colegio), en `users.plan`.
- `UsageEvent`: cada cosa que cuesta plata (segundos de audio por proveedor y
  modelo, minutos de voz, tokens del LLM) con su costo en dólares y los
  créditos que gastó. De acá salen los créditos del mes y el panel de consumo.
"""
import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin

# Planes de organización.
PLAN_BASE = "base"
PLAN_INSTITUTION = "institucion"
# Todo habilitado sin pagar (Northfield School, los usuarios de prueba).
PLAN_COURTESY = "cortesia"
# Planes individuales (los paga una persona).
PLAN_INDIVIDUAL = "individual"
PLAN_INDIVIDUAL_VOICE = "individual_voz"

ORG_PLANS = (PLAN_BASE, PLAN_INSTITUTION, PLAN_COURTESY)
USER_PLANS = (PLAN_BASE, PLAN_INDIVIDUAL, PLAN_INDIVIDUAL_VOICE)

# Claves de `limits` (todas opcionales; sin clave = sin tope):
#   credits_per_month        reuniones "con personas" por mes y por persona
#   people_hours_per_month   horas de reunión con personas incluidas por mes
#   voice_minutes_per_month  minutos de conversación por voz por mes
#   meetings_per_day         reuniones por día y por persona (contra abuso)
#   audio_hours_per_month    horas de audio transcripto por mes y por persona
LIMIT_KEYS = (
    "credits_per_month",
    "people_hours_per_month",
    "voice_minutes_per_month",
    "meetings_per_day",
    "audio_hours_per_month",
)

# Claves de `features`:
#   people: "always" (siempre se separa quién habló) | "credits" (gastando un crédito)
#   voice:  conversación por voz con el asistente
FEATURE_KEYS = ("people", "voice")


class BillingPlan(PKMixin, TimestampMixin, Base):
    __tablename__ = "billing_plans"

    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # organization | user | any (el plan Base vale para las dos)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    # Precio de lista en dólares por mes; None = no se muestra ("Contact sales").
    price_usd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    features: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class UsageEvent(PKMixin, TimestampMixin, Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_org_created", "organization_id", "created_at"),
        Index("ix_usage_user_created", "user_id", "created_at"),
        Index("ix_usage_meeting", "meeting_id"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL")
    )
    # stt_live | stt_final | voice | llm
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    # audio_seconds | voice_seconds | tokens
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    # Créditos del plan Base que gastó (una reunión con personas: 1 o 2).
    credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class PlanRequest(PKMixin, TimestampMixin, Base):
    """Alguien tocó "Suscribirme" o "Contact sales". Todavía no se cobra:
    queda el pedido y se avisa a Becode, que contacta a la persona."""

    __tablename__ = "plan_requests"
    __table_args__ = (Index("ix_plan_requests_created", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL")
    )
    plan: Mapped[str] = mapped_column(String(30), nullable=False)
    # new | contacted | done | cancelled
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new", nullable=False)
    message: Mapped[str | None] = mapped_column(String(1000))
