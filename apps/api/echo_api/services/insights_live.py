"""Extracción incremental de insights durante la reunión.

Cada ~8 segmentos finales se corre una pasada del LLM sobre la ventana nueva
del transcript. Si la organización no tiene LLM configurado, no se hace nada
y la UI lo indica claramente (sin simular resultados).
"""
import asyncio
import logging
import uuid

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import ActionItem, Decision, Meeting, Question, TranscriptSegment
from .ai_settings import resolve_llm
from .dates import resolve_relative_date
from .insights_prompts import LIVE_EXTRACT_SYSTEM, build_live_extract_prompt
from .live_bus import live_bus
from .llm import LLMError, get_llm_provider
from .transcript_util import load_transcript_lines, transcript_to_text

log = logging.getLogger("echo.insights")

_locks: dict[str, asyncio.Lock] = {}


async def maybe_extract_live_insights(meeting_id: str) -> None:
    lock = _locks.setdefault(meeting_id, asyncio.Lock())
    if lock.locked():
        return  # ya hay una extracción corriendo para esta reunión
    async with lock:
        try:
            await _extract(meeting_id)
        except Exception as exc:
            log.warning("live insights error meeting=%s: %s", meeting_id, exc)


async def _extract(meeting_id: str) -> None:
    mid = uuid.UUID(meeting_id)
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, mid)
        if not meeting or meeting.status not in ("live", "paused"):
            return
        config = await resolve_llm(db, meeting.organization_id)
        if config is None:
            return  # sin LLM configurado: la UI muestra "IA no configurada"

        state = meeting.processing_state or {}
        last_seq = int(state.get("live_extract_seq", 0))
        lines = await load_transcript_lines(db, mid, start_seq=last_seq + 1)
        if len(lines) < 3:
            return
        max_seq = max(line["seq"] for line in lines)

        # contexto: últimos items ya detectados para evitar duplicados
        existing_decisions = (
            (
                await db.execute(
                    select(Decision.text)
                    .where(Decision.meeting_id == mid)
                    .order_by(Decision.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        existing_tasks = (
            (
                await db.execute(
                    select(ActionItem.text)
                    .where(ActionItem.meeting_id == mid)
                    .order_by(ActionItem.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )

    provider = get_llm_provider(config.provider, config.api_key, config.model, config.base_url)
    window_text = transcript_to_text(lines)
    prompt = build_live_extract_prompt(window_text, list(existing_decisions), list(existing_tasks))
    try:
        result = await provider.chat_json(
            LIVE_EXTRACT_SYSTEM, [{"role": "user", "content": prompt}], temperature=0.1
        )
    except LLMError as exc:
        log.warning("live extract llm error: %s", exc)
        return
    if not isinstance(result, dict):
        return

    reference_date = None
    new_counts = {"decisions": 0, "tasks": 0, "questions": 0}
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, mid)
        if not meeting:
            return
        reference_date = (meeting.started_at or meeting.created_at).date()

        for item in result.get("decisions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text or _is_duplicate(text, existing_decisions):
                continue
            db.add(
                Decision(
                    meeting_id=mid,
                    organization_id=meeting.organization_id,
                    text=text,
                    context=item.get("context"),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
            new_counts["decisions"] += 1

        for item in result.get("tasks", []) or []:
            text = str(item.get("text", "")).strip()
            if not text or _is_duplicate(text, existing_tasks):
                continue
            due_text = item.get("due")
            db.add(
                ActionItem(
                    meeting_id=mid,
                    organization_id=meeting.organization_id,
                    text=text,
                    assignee_name=item.get("assignee"),
                    due_text=due_text,
                    due_date=resolve_relative_date(due_text, reference_date),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
            new_counts["tasks"] += 1

        for item in result.get("questions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Question(
                    meeting_id=mid,
                    organization_id=meeting.organization_id,
                    text=text,
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
            new_counts["questions"] += 1

        meeting.processing_state = {**(meeting.processing_state or {}), "live_extract_seq": max_seq}
        await db.commit()

        totals = {}
        for model, key in ((Decision, "decisions"), (ActionItem, "tasks"), (Question, "questions")):
            totals[key] = (
                await db.execute(select(func.count(model.id)).where(model.meeting_id == mid))
            ).scalar()

    await live_bus.publish(
        meeting_id,
        {"type": "insights", "totals": totals, "new": new_counts},
    )


def _is_duplicate(text: str, existing: list[str]) -> bool:
    normalized = text.lower().strip()
    return any(normalized in e.lower() or e.lower() in normalized for e in existing if e)


def _ms(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
