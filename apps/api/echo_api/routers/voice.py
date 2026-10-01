"""Conversación por voz con Echo (services/voice_agent.py).

- POST /api/voice/sessions: si el plan de la persona incluye voz y le quedan
  minutos del mes, devuelve una URL firmada de un solo uso para que el
  navegador hable con el agente (la key de ElevenLabs nunca sale del servidor).
  Si el agente todavía no existe, se crea en el momento.
- POST /api/voice/sessions/end: al cortar, se anota lo que ElevenLabs dice que
  duró. Si el navegador no avisa (cerró la pestaña), lo anota igual
  `reconcile_voice_usage`, que cada 10 minutos repasa las conversaciones del
  agente: el tope del mes no depende del navegador.
- GET/POST /api/admin/voice-agent: estado del agente, y crearlo o actualizarlo.
"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import OrgContext, get_org_context
from ..models import BillingPlan, ServerAISettings, UsageEvent, User
from ..services import plans, voice_agent
from ..services.audit import audit
from .admin import get_superadmin

log = logging.getLogger("echo.voice")

router = APIRouter(tags=["voice"])

RECONCILE_EVERY_SECONDS = 600


async def _settings_row(db: AsyncSession) -> ServerAISettings | None:
    return (await db.execute(select(ServerAISettings).limit(1))).scalar_one_or_none()


async def _agent_id(db: AsyncSession) -> str | None:
    row = await _settings_row(db)
    return row.voice_agent_id if row else None


async def ensure_agent(db: AsyncSession) -> str:
    """El id del agente; si no existe, lo crea y lo guarda."""
    row = await _settings_row(db)
    if row is not None and row.voice_agent_id:
        return row.voice_agent_id
    agent_id = await voice_agent.create_or_update_agent(None)
    if row is None:
        row = ServerAISettings(id=uuid.uuid4())
        db.add(row)
    row.voice_agent_id = agent_id
    await db.commit()
    log.info("agente de voz creado: %s", agent_id)
    return agent_id


async def voice_allowance(db: AsyncSession, user: User) -> tuple[bool, float | None, float]:
    """(tiene voz, segundos del mes (None = sin tope), segundos usados)."""
    if user.is_superadmin:
        # Las cuentas de Becode tienen todo habilitado, sin tope.
        return True, None, (await plans.month_usage(db, user.id)).voice_seconds
    plan = (await db.execute(select(BillingPlan).where(BillingPlan.code == user.plan))).scalar_one_or_none()
    if plan is None or not (plan.features or {}).get("voice"):
        return False, None, 0.0
    limits = plans._limits(plan.limits, user.limits)
    minutes = limits.get("voice_minutes_per_month")
    used = (await plans.month_usage(db, user.id)).voice_seconds
    return True, (float(minutes) * 60 if minutes is not None else None), used


class SessionOut(BaseModel):
    signed_url: str
    max_seconds: int
    seconds_left: int | None
    user_name: str
    # Lo que el navegador le pasa al agente al abrir la conversación.
    dynamic_variables: dict[str, str]


@router.post("/api/voice/sessions", response_model=SessionOut)
async def start_session(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    allowed, total, used = await voice_allowance(db, ctx.user)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La conversación por voz es parte del plan Individual + voz.")
    left = None if total is None else max(0.0, total - used)
    if left is not None and left < 10:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya usaste los minutos de voz de este mes. Se renuevan el 1°.")
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La conversación por voz no está configurada en el servidor.")
    try:
        agent_id = await ensure_agent(db)
        url = await voice_agent.signed_url(agent_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("voz: no se pudo abrir la conversación: %s", exc)
        detail = "No se pudo conectar con la voz. Probá de nuevo en un momento."
        if ctx.user.is_superadmin:
            detail += f" (ElevenLabs: {str(exc)[:200]})"
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail) from exc
    max_seconds = (
        voice_agent.MAX_CONVERSATION_SECONDS if left is None else min(voice_agent.MAX_CONVERSATION_SECONDS, int(left))
    )
    first_name = (ctx.user.name or "").split(" ")[0]
    return SessionOut(
        signed_url=url,
        max_seconds=max_seconds,
        seconds_left=None if left is None else int(left),
        user_name=first_name,
        dynamic_variables={"user_name": first_name, "echo_user": str(ctx.user.id), "echo_org": str(ctx.org_id)},
    )


async def _already_recorded(db: AsyncSession, conversation_id: str) -> bool:
    return (
        await db.execute(
            select(UsageEvent.id).where(
                UsageEvent.kind == "voice", UsageEvent.meta["conversation_id"].astext == conversation_id
            )
        )
    ).first() is not None


async def _record(
    db: AsyncSession, conversation_id: str, seconds: float, user_id: uuid.UUID, org_id: uuid.UUID | None, source: str
) -> None:
    await plans.record_usage(
        db, kind="voice", provider="elevenlabs", model=voice_agent.TTS_MODEL, unit="voice_seconds",
        quantity=round(seconds, 1), cost_usd=voice_agent.voice_cost(seconds),
        organization_id=org_id, user_id=user_id,
        meta={"conversation_id": conversation_id, "measured_by": source, "llm": voice_agent.AGENT_LLM},
    )


class EndIn(BaseModel):
    conversation_id: str = Field(min_length=4, max_length=120)
    # Lo que midió el navegador. No se usa para cobrar: solo informativo.
    seconds: float = Field(default=0, ge=0, le=3600)


class EndOut(BaseModel):
    seconds: float
    seconds_left: int | None
    # True: ElevenLabs todavía no cerró la conversación; se anota sola después.
    pending: bool = False


@router.post("/api/voice/sessions/end", response_model=EndOut)
async def end_session(data: EndIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    _, total, used = await voice_allowance(db, ctx.user)

    def left(extra: float = 0.0) -> int | None:
        return None if total is None else int(max(0.0, total - used - extra))

    if await _already_recorded(db, data.conversation_id):
        return EndOut(seconds=0, seconds_left=left())
    agent_id = await _agent_id(db)
    try:
        details = await voice_agent.conversation_details(data.conversation_id)
    except Exception as exc:  # noqa: BLE001 - lo anota la conciliación más tarde
        log.info("voz: sin detalle de %s todavía: %s", data.conversation_id, exc)
        return EndOut(seconds=0, seconds_left=left(), pending=True)
    owner, _ = voice_agent.conversation_owner(details)
    if (agent_id and details.get("agent_id") != agent_id) or (owner and owner != str(ctx.user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
    seconds = (details.get("metadata") or {}).get("call_duration_secs")
    if details.get("status") not in ("done", "failed") or seconds is None:
        # Todavía abierta: anotar ahora dejaría gratis el resto de la charla.
        return EndOut(seconds=0, seconds_left=left(), pending=True)
    await _record(db, data.conversation_id, float(seconds), ctx.user.id, ctx.org_id, "elevenlabs")
    await db.commit()
    return EndOut(seconds=float(seconds), seconds_left=left(float(seconds)))


async def reconcile_voice_usage() -> int:
    """Anota las conversaciones terminadas que nadie anotó (pestaña cerrada,
    se cortó internet). Devuelve cuántas anotó."""
    if not get_settings().elevenlabs_api_key:
        return 0
    async with SessionLocal() as db:
        agent_id = await _agent_id(db)
    if not agent_id:
        return 0
    recorded = 0
    for item in await voice_agent.recent_conversations(agent_id):
        conversation_id = item.get("conversation_id")
        if not conversation_id or item.get("status") not in ("done", "failed"):
            continue
        async with SessionLocal() as db:
            if await _already_recorded(db, conversation_id):
                continue
            details = await voice_agent.conversation_details(conversation_id)
            owner, org = voice_agent.conversation_owner(details)
            seconds = (details.get("metadata") or {}).get("call_duration_secs") or item.get("call_duration_secs")
            if not owner or seconds is None:
                continue
            try:
                user_id = uuid.UUID(owner)
                org_id = uuid.UUID(org) if org else None
            except ValueError:
                continue
            if await db.get(User, user_id) is None:
                continue
            await _record(db, conversation_id, float(seconds), user_id, org_id, "conciliacion")
            await db.commit()
            recorded += 1
    return recorded


async def reconcile_loop(interval_seconds: int = RECONCILE_EVERY_SECONDS) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            recorded = await reconcile_voice_usage()
            if recorded:
                log.info("voz: %s conversaciones anotadas por conciliación", recorded)
        except Exception:  # noqa: BLE001 - nunca tira abajo la API
            log.exception("voz: falló la conciliación del consumo")


class AgentOut(BaseModel):
    agent_id: str | None
    voice_id: str
    llm: str
    ok: bool
    detail: str


@router.get("/api/admin/voice-agent", response_model=AgentOut)
async def agent_state(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    agent_id = await _agent_id(db)
    try:
        ok, detail = await voice_agent.agent_status(agent_id)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"No se pudo consultar ElevenLabs: {exc}"
    return AgentOut(agent_id=agent_id, voice_id=voice_agent.current_voice_id(), llm=voice_agent.AGENT_LLM, ok=ok, detail=detail)


@router.post("/api/admin/voice-agent", response_model=AgentOut)
async def setup_agent(admin: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    """Crea el agente de Echo en ElevenLabs, o lo actualiza con el prompt, la voz y el LLM de hoy."""
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Falta ELEVENLABS_API_KEY en el servidor")
    row = await _settings_row(db)
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
    try:
        ok, detail = await voice_agent.agent_status(row.voice_agent_id)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    return AgentOut(
        agent_id=row.voice_agent_id, voice_id=voice_agent.current_voice_id(), llm=voice_agent.AGENT_LLM, ok=ok, detail=detail
    )
