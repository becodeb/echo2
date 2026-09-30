"""Conversación por voz con Echo (services/voice_agent.py).

- POST /api/voice/sessions: si el plan de la persona incluye voz y le quedan
  minutos del mes, devuelve una URL firmada de un solo uso para que el
  navegador hable con el agente (la key de ElevenLabs nunca sale del servidor).
- POST /api/voice/sessions/end: al cortar, el servidor le pregunta a
  ElevenLabs cuánto duró de verdad la conversación y la anota en el consumo.
- POST /api/admin/voice-agent: un superadmin crea o actualiza el agente con
  la key de la instalación.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import BillingPlan, ServerAISettings, UsageEvent, User
from ..services import plans, voice_agent
from ..services.audit import audit
from .admin import get_superadmin

log = logging.getLogger("echo.voice")

router = APIRouter(tags=["voice"])


async def _agent_id(db: AsyncSession) -> str | None:
    row = (await db.execute(select(ServerAISettings).limit(1))).scalar_one_or_none()
    return row.voice_agent_id if row else None


async def voice_allowance(db: AsyncSession, user: User) -> tuple[bool, float | None, float]:
    """(tiene voz, segundos del mes (None = sin tope), segundos usados)."""
    if user.is_superadmin:
        # Las cuentas de Becode tienen todo habilitado, sin tope.
        return True, None, (await plans.month_usage(db, user.id)).voice_seconds
    plan = (await db.execute(select(BillingPlan).where(BillingPlan.code == user.plan))).scalar_one_or_none()
    if plan is None or not (plan.features or {}).get("voice"):
        return False, None, 0.0
    limits = {**(plan.limits or {}), **(user.limits or {})}
    minutes = limits.get("voice_minutes_per_month")
    used = (await plans.month_usage(db, user.id)).voice_seconds
    return True, (float(minutes) * 60 if minutes is not None else None), used


class SessionOut(BaseModel):
    signed_url: str
    max_seconds: int
    seconds_left: int | None
    user_name: str


@router.post("/api/voice/sessions", response_model=SessionOut)
async def start_session(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    allowed, total, used = await voice_allowance(db, ctx.user)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La conversación por voz es parte del plan Individual + voz.")
    left = None if total is None else max(0.0, total - used)
    if left is not None and left < 10:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya usaste los minutos de voz de este mes. Se renuevan el 1°.")
    agent_id = await _agent_id(db)
    if not agent_id or not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La conversación por voz todavía no está disponible.")
    try:
        url = await voice_agent.signed_url(agent_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("voz: no se pudo abrir la conversación: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo conectar con la voz. Probá de nuevo.") from exc
    max_seconds = voice_agent.MAX_CONVERSATION_SECONDS if left is None else min(voice_agent.MAX_CONVERSATION_SECONDS, int(left))
    return SessionOut(
        signed_url=url,
        max_seconds=max_seconds,
        seconds_left=None if left is None else int(left),
        user_name=(ctx.user.name or "").split(" ")[0],
    )


class EndIn(BaseModel):
    conversation_id: str = Field(min_length=4, max_length=120)
    # Lo que midió el navegador: solo si ElevenLabs todavía no informa la duración.
    seconds: float = Field(default=0, ge=0, le=3600)


class EndOut(BaseModel):
    seconds: float
    seconds_left: int | None


@router.post("/api/voice/sessions/end", response_model=EndOut)
async def end_session(data: EndIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    already = (
        await db.execute(
            select(UsageEvent.id).where(
                UsageEvent.kind == "voice", UsageEvent.meta["conversation_id"].astext == data.conversation_id
            )
        )
    ).first()
    allowed, total, used = await voice_allowance(db, ctx.user)
    if already:
        return EndOut(seconds=0, seconds_left=None if total is None else int(max(0.0, total - used)))
    agent_id = await _agent_id(db)
    seconds = min(data.seconds, voice_agent.MAX_CONVERSATION_SECONDS)
    source = "browser"
    try:
        details = await voice_agent.conversation_details(data.conversation_id)
        if agent_id and details.get("agent_id") and details["agent_id"] != agent_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
        measured = (details.get("metadata") or {}).get("call_duration_secs")
        if measured is not None:
            seconds, source = float(measured), "elevenlabs"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - se anota lo que midió el navegador
        log.info("voz: sin duración de ElevenLabs para %s: %s", data.conversation_id, exc)
    await plans.record_usage(
        db, kind="voice", provider="elevenlabs", model=voice_agent.TTS_MODEL, unit="voice_seconds",
        quantity=round(seconds, 1), cost_usd=voice_agent.voice_cost(seconds),
        organization_id=ctx.org_id, user_id=ctx.user.id,
        meta={"conversation_id": data.conversation_id, "measured_by": source, "llm": voice_agent.AGENT_LLM},
    )
    await db.commit()
    return EndOut(seconds=seconds, seconds_left=None if total is None else int(max(0.0, total - used - seconds)))


class AgentOut(BaseModel):
    agent_id: str
    voice_id: str
    llm: str


@router.post("/api/admin/voice-agent", response_model=AgentOut)
async def setup_agent(admin: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    """Crea el agente de Echo en ElevenLabs, o lo actualiza con el prompt, la voz y el LLM de hoy."""
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Falta ELEVENLABS_API_KEY en el servidor")
    row = (await db.execute(select(ServerAISettings).limit(1))).scalar_one_or_none()
    if row is None:
        row = ServerAISettings(id=uuid.uuid4())
        db.add(row)
    try:
        row.voice_agent_id = await voice_agent.create_or_update_agent(row.voice_agent_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ElevenLabs rechazó el agente: {exc}") from exc
    row.updated_by = admin.id
    await audit(db, None, admin.id, "admin.voice_agent", "voice_agent", row.voice_agent_id, detail={"by": admin.email})
    await db.commit()
    voice = get_settings().elevenlabs_agent_voice_id or voice_agent.DEFAULT_VOICE_ID
    return AgentOut(agent_id=row.voice_agent_id, voice_id=voice, llm=voice_agent.AGENT_LLM)
