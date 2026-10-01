"""Conversación por voz con Echo (services/voice_agent.py). El tope lo aplica el servidor.

- GET /api/voice/status: si la persona tiene voz y cuánto le queda del mes.
- POST /api/voice/sessions: registra la sesión (voice_sessions) y devuelve una
  URL firmada de un solo uso del agente cuya duración máxima entra en lo que
  le queda (ElevenLabs no deja cambiar la duración por conversación: hay un
  agente por duración). De a una charla abierta por persona; la que nadie
  cerró vence sola.
- POST /api/voice/sessions/end: al cortar, se anota lo que ElevenLabs dice que
  duró, contra la sesión que entregó el servidor (no contra lo que diga el
  navegador). Sin conversación (se cerró antes de conectar), la libera.
- reconcile_voice_usage, cada 10 minutos: anota las conversaciones
  terminadas que nadie anotó, por el id de sesión que viaja en la charla. Lo
  que no concilia (alguien borró o cambió la variable) se le cobra a la
  última sesión entregada antes de que empezara, y se avisa al superadmin.
- GET/POST /api/admin/voice-agent: estado de los agentes, y crearlos o
  actualizarlos.
"""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import OrgContext, get_org_context
from ..models import Notification, OrganizationMember, ServerAISettings, UsageEvent, User, VoiceSession
from ..services import plans, voice_agent
from ..services.audit import audit
from .admin import get_superadmin

log = logging.getLogger("echo.voice")

router = APIRouter(tags=["voice"])

RECONCILE_EVERY_SECONDS = 600
# Una sesión que nadie cerró deja de contar como abierta esto después de su tope.
OPEN_GRACE_SECONDS = 120
# Lock de Postgres para crear los agentes de a uno (dos charlas a la vez no
# crean dos agentes).
AGENTS_LOCK = 0x45_43_48_4F_56  # "ECHOV"


async def _settings_row(db: AsyncSession) -> ServerAISettings | None:
    return (await db.execute(select(ServerAISettings).limit(1))).scalar_one_or_none()


def _agents_of(row: ServerAISettings | None) -> dict[str, str]:
    agents = dict((row.voice_agents or {}) if row else {})
    if row is not None and row.voice_agent_id and str(voice_agent.MAX_CONVERSATION_SECONDS) not in agents:
        agents[str(voice_agent.MAX_CONVERSATION_SECONDS)] = row.voice_agent_id
    return agents


async def ensure_agents(db: AsyncSession, update: bool = False) -> dict[str, str]:
    """Los agentes por duración; crea los que falten. Con `update` (o si
    cambió la configuración) los pone al día. Uno a la vez en todo el servidor."""
    await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": AGENTS_LOCK})
    row = await _settings_row(db)
    if row is None:
        row = ServerAISettings(id=uuid.uuid4())
        db.add(row)
    agents = _agents_of(row)
    wanted = voice_agent.config_hash()
    changed = update or row.voice_agent_hash != wanted
    for seconds in voice_agent.BUCKETS:
        key = str(seconds)
        if key not in agents:
            agents[key] = await voice_agent.create_or_update_agent(None, max_seconds=seconds)
            log.info("agente de voz de %s s creado: %s", seconds, agents[key])
        elif changed:
            await voice_agent.create_or_update_agent(agents[key], max_seconds=seconds)
    row.voice_agents = agents
    row.voice_agent_id = agents[str(voice_agent.MAX_CONVERSATION_SECONDS)]
    row.voice_agent_hash = wanted
    await db.commit()
    return agents


async def voice_allowance(db: AsyncSession, user: User) -> tuple[bool, float | None, float]:
    return await plans.voice_allowance(db, user)


class StatusOut(BaseModel):
    allowed: bool
    # None = sin tope (superadmins).
    seconds_total: int | None
    seconds_left: int | None
    seconds_used: int
    max_conversation_seconds: int


@router.get("/api/voice/status", response_model=StatusOut)
async def voice_status(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    """Para la pantalla previa del globito: si tiene voz y cuánto le queda."""
    allowed, total, used = await voice_allowance(db, ctx.user)
    left = None if total is None else max(0.0, total - used)
    return StatusOut(
        allowed=allowed,
        seconds_total=None if total is None else int(total),
        seconds_left=None if left is None else int(left),
        seconds_used=int(used),
        max_conversation_seconds=voice_agent.bucket_for(left) or 0,
    )


class SessionOut(BaseModel):
    session_id: uuid.UUID
    signed_url: str
    max_seconds: int
    seconds_left: int | None
    user_name: str
    # Lo que el navegador le pasa al agente al abrir la conversación.
    dynamic_variables: dict[str, str]


async def _open_session(db: AsyncSession, user_id: uuid.UUID) -> VoiceSession | None:
    return (
        await db.execute(
            select(VoiceSession).where(
                VoiceSession.user_id == user_id,
                VoiceSession.ended_at.is_(None),
                VoiceSession.expires_at > datetime.now(UTC),
            )
        )
    ).scalars().first()


@router.post("/api/voice/sessions", response_model=SessionOut)
async def start_session(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    allowed, total, used = await voice_allowance(db, ctx.user)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La conversación por voz es parte del plan Individual + voz.")
    left = None if total is None else max(0.0, total - used)
    bucket = voice_agent.bucket_for(left)
    if bucket is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya usaste los minutos de voz de este mes. Se renuevan el 1°.")
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La conversación por voz no está configurada en el servidor.")
    # De a una por persona: dos pestañas a la vez no duplican los minutos.
    await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx.user.id.int % (2**63 - 1)})
    if await _open_session(db, ctx.user.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya tenés una charla abierta con Echo. Cortala para empezar otra.")
    try:
        agent_id = (await ensure_agents(db))[str(bucket)]
        url = await voice_agent.signed_url(agent_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("voz: no se pudo abrir la conversación: %s", exc)
        detail = "No se pudo conectar con la voz. Probá de nuevo en un momento."
        if ctx.user.is_superadmin:
            detail += f" (ElevenLabs: {str(exc)[:200]})"
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail) from exc
    await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx.user.id.int % (2**63 - 1)})
    if await _open_session(db, ctx.user.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya tenés una charla abierta con Echo. Cortala para empezar otra.")
    session = VoiceSession(
        id=uuid.uuid4(), user_id=ctx.user.id, organization_id=ctx.org_id, allowed_seconds=bucket, agent_id=agent_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=bucket + OPEN_GRACE_SECONDS),
    )
    db.add(session)
    await db.commit()
    first_name = (ctx.user.name or "").split(" ")[0]
    return SessionOut(
        session_id=session.id,
        signed_url=url,
        max_seconds=bucket,
        seconds_left=None if left is None else int(left),
        user_name=first_name,
        dynamic_variables={"user_name": first_name, "echo_session": str(session.id)},
    )


async def _already_recorded(db: AsyncSession, conversation_id: str) -> bool:
    return (
        await db.execute(
            select(UsageEvent.id).where(
                UsageEvent.kind == "voice", UsageEvent.meta["conversation_id"].astext == conversation_id
            )
        )
    ).first() is not None


def _llm_price(details: dict) -> float | None:
    """Lo que ElevenLabs cobró aparte por el LLM del agente, si lo informa."""
    price = ((details.get("metadata") or {}).get("charging") or {}).get("llm_price")
    return float(price) if isinstance(price, int | float) and not isinstance(price, bool) else None


async def _record(
    db: AsyncSession,
    session: VoiceSession,
    conversation_id: str,
    seconds: float,
    source: str,
    details: dict | None = None,
) -> None:
    llm_usd = _llm_price(details or {})
    await plans.record_usage(
        db, kind="voice", provider="elevenlabs", model=voice_agent.TTS_MODEL, unit="voice_seconds",
        quantity=round(seconds, 1), cost_usd=voice_agent.voice_cost(seconds) + (llm_usd or 0.0),
        organization_id=session.organization_id, user_id=session.user_id,
        meta={
            "conversation_id": conversation_id, "session_id": str(session.id), "measured_by": source,
            "llm": voice_agent.AGENT_LLM, **({"llm_usd": llm_usd} if llm_usd is not None else {}),
        },
    )
    session.conversation_id = conversation_id
    session.seconds = round(seconds, 1)
    session.ended_at = session.ended_at or datetime.now(UTC)


class EndIn(BaseModel):
    session_id: uuid.UUID
    # Sin conversación: se cerró antes de conectar (se libera la sesión).
    conversation_id: str | None = Field(default=None, min_length=4, max_length=120)
    # Lo que midió el navegador. No se usa para cobrar: solo informativo.
    seconds: float = Field(default=0, ge=0, le=3600)


class EndOut(BaseModel):
    seconds: float
    seconds_left: int | None
    # True: ElevenLabs todavía no cerró la conversación; se anota sola después.
    pending: bool = False


@router.post("/api/voice/sessions/end", response_model=EndOut)
async def end_session(data: EndIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    session = await db.get(VoiceSession, data.session_id)
    if session is None or session.user_id != ctx.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesión no encontrada")
    _, total, used = await voice_allowance(db, ctx.user)

    def left(extra: float = 0.0) -> int | None:
        return None if total is None else int(max(0.0, total - used - extra))

    if data.conversation_id is None:
        if session.conversation_id is None:
            session.ended_at = session.ended_at or datetime.now(UTC)
            await db.commit()
        return EndOut(seconds=0, seconds_left=left())
    if session.conversation_id not in (None, data.conversation_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esa sesión ya tiene otra conversación")
    if await _already_recorded(db, data.conversation_id):
        return EndOut(seconds=0, seconds_left=left())
    try:
        details = await voice_agent.conversation_details(data.conversation_id)
    except Exception as exc:  # noqa: BLE001 - lo anota la conciliación más tarde
        log.info("voz: sin detalle de %s todavía: %s", data.conversation_id, exc)
        return EndOut(seconds=0, seconds_left=left(), pending=True)
    claimed = voice_agent.conversation_session(details)
    if details.get("agent_id") != session.agent_id or (claimed and claimed != str(session.id)):
        # La conversación es de otra sesión (o de otro agente): no se anota acá.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
    seconds = (details.get("metadata") or {}).get("call_duration_secs")
    if details.get("status") not in ("done", "failed") or seconds is None:
        # Todavía abierta: anotar ahora dejaría gratis el resto de la charla.
        return EndOut(seconds=0, seconds_left=left(), pending=True)
    await _record(db, session, data.conversation_id, float(seconds), "elevenlabs", details)
    await db.commit()
    return EndOut(seconds=float(seconds), seconds_left=left(float(seconds)))


async def _alert_superadmins(db: AsyncSession, title: str, body: str) -> None:
    admins = (await db.execute(select(User.id).where(User.is_superadmin.is_(True)))).scalars().all()
    for admin_id in admins:
        org_id = (
            await db.execute(
                select(OrganizationMember.organization_id).where(OrganizationMember.user_id == admin_id).limit(1)
            )
        ).scalar_one_or_none()
        if org_id is not None:
            db.add(Notification(user_id=admin_id, organization_id=org_id, kind="voice_unmatched",
                                title=title[:300], body=body, link="/admin"))


async def _session_for(db: AsyncSession, details: dict, agent_id: str) -> tuple[VoiceSession | None, bool]:
    """(sesión, concilió por su id). Si el id no concilia, la última sesión
    entregada con ese agente antes de que empezara la conversación."""
    claimed = voice_agent.conversation_session(details)
    if claimed:
        try:
            session = await db.get(VoiceSession, uuid.UUID(claimed))
        except ValueError:
            session = None
        if session is not None and session.agent_id == agent_id and session.conversation_id is None:
            return session, True
    started = voice_agent.conversation_start(details)
    query = select(VoiceSession).where(VoiceSession.agent_id == agent_id, VoiceSession.conversation_id.is_(None))
    if started is not None:
        query = query.where(VoiceSession.created_at <= datetime.fromtimestamp(started + 60, UTC))
    return (await db.execute(query.order_by(VoiceSession.created_at.desc()).limit(1))).scalars().first(), False


async def reconcile_voice_usage() -> int:
    """Anota las conversaciones terminadas que nadie anotó (pestaña cerrada,
    se cortó internet, o alguien tocó la charla). Devuelve cuántas anotó."""
    if not get_settings().elevenlabs_api_key:
        return 0
    async with SessionLocal() as db:
        agents = _agents_of(await _settings_row(db))
    recorded = 0
    for agent_id in dict.fromkeys(agents.values()):
        for item in await voice_agent.recent_conversations(agent_id):
            conversation_id = item.get("conversation_id")
            if not conversation_id or item.get("status") not in ("done", "failed"):
                continue
            async with SessionLocal() as db:
                if await _already_recorded(db, conversation_id):
                    continue
                details = await voice_agent.conversation_details(conversation_id)
                seconds = (details.get("metadata") or {}).get("call_duration_secs") or item.get("call_duration_secs")
                if seconds is None:
                    continue
                session, matched = await _session_for(db, details, agent_id)
                if session is None:
                    await _alert_superadmins(
                        db, "Charla de voz sin sesión",
                        f"La conversación {conversation_id} ({int(seconds)} s) no tiene una sesión de Echo: no se le cobró a nadie.",
                    )
                    await plans.record_usage(
                        db, kind="voice", provider="elevenlabs", model=voice_agent.TTS_MODEL, unit="voice_seconds",
                        quantity=round(float(seconds), 1), cost_usd=voice_agent.voice_cost(float(seconds)),
                        organization_id=None, user_id=None,
                        meta={"conversation_id": conversation_id, "measured_by": "conciliacion", "unmatched": True},
                    )
                else:
                    await _record(db, session, conversation_id, float(seconds), "conciliacion", details)
                    if not matched:
                        owner = await db.get(User, session.user_id)
                        await _alert_superadmins(
                            db, "Charla de voz conciliada a mano",
                            f"La conversación {conversation_id} ({int(seconds)} s) no traía su sesión: se le anotó a "
                            f"{owner.email if owner else session.user_id}, la última sesión entregada.",
                        )
                await db.commit()
                recorded += 1
    async with SessionLocal() as db:
        # Las que nadie cerró ni concilió: dejan de figurar abiertas.
        stale = (
            await db.execute(
                select(VoiceSession).where(VoiceSession.ended_at.is_(None), VoiceSession.expires_at < datetime.now(UTC))
            )
        ).scalars().all()
        for session in stale:
            session.ended_at = session.expires_at
        await db.commit()
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
    agents: dict[str, str] = {}
    voice_id: str
    llm: str
    ok: bool
    detail: str


@router.get("/api/admin/voice-agent", response_model=AgentOut)
async def agent_state(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    agents = _agents_of(await _settings_row(db))
    agent_id = agents.get(str(voice_agent.MAX_CONVERSATION_SECONDS))
    try:
        ok, detail = await voice_agent.agent_status(agent_id)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"No se pudo consultar ElevenLabs: {exc}"
    return AgentOut(agent_id=agent_id, agents=agents, voice_id=voice_agent.current_voice_id(),
                    llm=voice_agent.AGENT_LLM, ok=ok, detail=detail)


@router.post("/api/admin/voice-agent", response_model=AgentOut)
async def setup_agent(admin: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    """Crea los agentes de Echo en ElevenLabs, o los actualiza con el prompt, la voz y el LLM de hoy."""
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Falta ELEVENLABS_API_KEY en el servidor")
    try:
        agents = await ensure_agents(db, update=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ElevenLabs rechazó el agente: {exc}") from exc
    agent_id = agents[str(voice_agent.MAX_CONVERSATION_SECONDS)]
    await audit(db, None, admin.id, "admin.voice_agent", "voice_agent", agent_id, detail={"by": admin.email})
    await db.commit()
    try:
        ok, detail = await voice_agent.agent_status(agent_id)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    return AgentOut(agent_id=agent_id, agents=agents, voice_id=voice_agent.current_voice_id(),
                    llm=voice_agent.AGENT_LLM, ok=ok, detail=detail)
