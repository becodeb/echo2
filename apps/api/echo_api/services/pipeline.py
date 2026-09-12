"""Pipeline de finalización de reunión.

Al tocar "Finalizar" corre en background:
  1. consolidar hablantes (hints de diarización → Speaker rows)
  2. sugerir identidades por voice profile (si hay embeddings de speaker)
  3. extracción estructurada final (temas, decisiones, tareas, etc.)
  4. resolución de fechas relativas
  5. embeddings del transcript (RAG)
  6. resúmenes (jerárquicos si la reunión es larga)
  7. generación + verificación del acta (arranca en paralelo apenas hay
     extracción: es lo primero que se quiere ver al terminar)
  8. actualización de la memoria organizacional
  9. sugerencia de reuniones relacionadas
 10. notificaciones

Cada etapa reporta progreso vía live_bus y processing_state. Si el LLM no está
configurado, las etapas de IA se saltean y quedan marcadas como "skipped"
(la UI lo muestra; nada se simula).
"""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from ..db import SessionLocal
from ..models import (
    ActionItem,
    Bookmark,
    Decision,
    Meeting,
    MeetingParticipant,
    MeetingSummary,
    MeetingTopic,
    Notification,
    OrganizationMember,
    Question,
    Risk,
    Speaker,
    TranscriptSegment,
)
from .ai_settings import resolve_embeddings, resolve_llm
from .dates import resolve_relative_date
from .insights_prompts import (
    FINAL_EXTRACT_SYSTEM,
    SECTION_SUMMARY_SYSTEM,
    SUMMARY_SYSTEM,
    build_final_extract_prompt,
    build_section_summary_prompt,
    build_summary_prompt,
)
from .live_bus import live_bus
from .llm import LLMError, get_llm_provider
from .memory_svc import update_memory_from_meeting
from .minutes_gen import generate_minutes
from .rag import embed_meeting_segments
from .transcript_util import format_ms, load_transcript_lines, transcript_to_text

log = logging.getLogger("echo.pipeline")

SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

# Si el transcript supera este tamaño se procesa jerárquicamente
SINGLE_PASS_CHAR_LIMIT = 24000


async def _set_stage(meeting_id: uuid.UUID, stage: str, progress: int, extra: dict | None = None) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        state = dict(meeting.processing_state or {})
        state.update({"stage": stage, "progress": progress})
        if extra:
            state.update(extra)
        meeting.processing_state = state
        await db.commit()
    await live_bus.publish(
        str(meeting_id), {"type": "processing", "stage": stage, "progress": progress}
    )


async def run_finalize_pipeline(meeting_id_str: str) -> None:
    meeting_id = uuid.UUID(meeting_id_str)
    try:
        await _run(meeting_id)
    except Exception as exc:
        log.exception("pipeline fallo meeting=%s", meeting_id)
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting:
                meeting.status = "failed"
                meeting.processing_state = {
                    **(meeting.processing_state or {}),
                    "stage": "failed",
                    "error": str(exc)[:500],
                }
                await db.commit()
        await live_bus.publish(meeting_id_str, {"type": "status", "status": "failed"})


async def _run(meeting_id: uuid.UUID) -> None:
    skipped: list[str] = []

    # 1. Consolidar hablantes
    await _set_stage(meeting_id, "speakers", 5)
    await consolidate_speakers(meeting_id)

    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id
        language = meeting.language
        reference_date = (meeting.started_at or meeting.created_at).date()
        llm_config = await resolve_llm(db, org_id)
        embeddings_config = await resolve_embeddings(db, org_id)
        lines = await load_transcript_lines(db, meeting_id)
        bookmarks = (
            (
                await db.execute(
                    select(Bookmark).where(Bookmark.meeting_id == meeting_id).order_by(Bookmark.at_ms)
                )
            )
            .scalars()
            .all()
        )
        bookmarks_text = "\n".join(
            f"[{format_ms(b.at_ms)}] {b.kind.upper()}: {b.note or '(sin nota)'}" for b in bookmarks
        )

    if not lines:
        # reunión sin transcript: completar directamente
        await _finish(meeting_id, skipped + ["sin_transcript"])
        return

    provider = None
    if llm_config:
        provider = get_llm_provider(
            llm_config.provider, llm_config.api_key, llm_config.model, llm_config.base_url
        )

    # 3. Extracción estructurada final
    insights: dict = {}
    if provider:
        await _set_stage(meeting_id, "insights", 20)
        try:
            insights = await _extract_final(provider, lines, bookmarks_text)
            await _persist_insights(meeting_id, insights, reference_date)
        except LLMError as exc:
            log.warning("extraccion final fallo: %s", exc)
            skipped.append(f"insights:{exc}")
    else:
        skipped.append("insights:llm_no_configurado")

    # 4. Acta: arranca apenas hay insights y corre en paralelo con embeddings y
    #    resúmenes. Es lo primero que la persona quiere ver al terminar, así
    #    que no espera a nada más. generate_minutes registra sus propias fallas.
    minutes_task: asyncio.Task | None = None
    if provider:
        await _set_stage(meeting_id, "minutes", 30)
        minutes_task = asyncio.create_task(generate_minutes(meeting_id, provider))
    else:
        skipped.append("minutes:llm_no_configurado")

    # 5. Embeddings para RAG
    if embeddings_config:
        await _set_stage(meeting_id, "embeddings", 45)
        try:
            await embed_meeting_segments(meeting_id, embeddings_config)
        except Exception as exc:
            log.warning("embeddings fallo: %s", exc)
            skipped.append(f"embeddings:{exc}")
    else:
        skipped.append("embeddings:no_configurado")

    # 6. Resúmenes
    if provider:
        await _set_stage(meeting_id, "summary", 60)
        try:
            await _generate_summaries(provider, meeting_id, org_id, language, lines, insights)
        except LLMError as exc:
            log.warning("resumen fallo: %s", exc)
            skipped.append(f"summary:{exc}")

    # 7. Esperar el acta si todavía no terminó (generación + verificación)
    if minutes_task is not None:
        if not minutes_task.done():
            await _set_stage(meeting_id, "minutes", 75)
        try:
            await minutes_task
        except Exception as exc:  # noqa: BLE001 - generate_minutes ya dejó registrada la falla
            log.warning("acta fallo: %s", exc)
            skipped.append(f"minutes:{exc}")

    # 8. Memoria organizacional
    if provider:
        await _set_stage(meeting_id, "memory", 88)
        try:
            await update_memory_from_meeting(meeting_id, insights, embeddings_config)
        except Exception as exc:
            log.warning("memoria fallo: %s", exc)
            skipped.append(f"memory:{exc}")

    await _finish(meeting_id, skipped)


async def _finish(meeting_id: uuid.UUID, skipped: list[str]) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        meeting.status = "completed"
        meeting.processing_state = {
            "stage": "done",
            "progress": 100,
            "skipped": skipped,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        # notificar a los miembros: acta lista
        members = (
            (
                await db.execute(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == meeting.organization_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in members:
            db.add(
                Notification(
                    user_id=user_id,
                    organization_id=meeting.organization_id,
                    kind="minutes_ready",
                    title=f"La reunión «{meeting.title}» está lista",
                    body="Resumen, decisiones, tareas y acta disponibles.",
                    link=f"/meetings/{meeting.id}",
                )
            )
        await db.commit()
    await live_bus.publish(str(meeting_id), {"type": "status", "status": "completed"})


# ── Hablantes ────────────────────────────────────────────────────


async def consolidate_speakers(meeting_id: uuid.UUID) -> None:
    """Agrupa speaker_hints en filas Speaker y las asigna a los segmentos."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        hints = (
            await db.execute(
                select(TranscriptSegment.speaker_hint, func.min(TranscriptSegment.seq))
                .where(TranscriptSegment.meeting_id == meeting_id)
                .group_by(TranscriptSegment.speaker_hint)
                .order_by(func.min(TranscriptSegment.seq))
            )
        ).all()
        if not hints:
            return

        existing = {
            s.label: s
            for s in (
                (await db.execute(select(Speaker).where(Speaker.meeting_id == meeting_id)))
                .scalars()
                .all()
            )
        }

        index = len(existing)
        hint_to_speaker: dict[str | None, Speaker] = {}
        for hint, _first_seq in hints:
            label = f"Speaker {index + 1}" if hint is None or hint not in existing else hint
            if hint is not None and hint.startswith("speaker_"):
                # hints normalizados del bridge: speaker_1, speaker_2...
                label = "Speaker " + hint.removeprefix("speaker_")
            speaker = existing.get(label)
            if not speaker:
                speaker = Speaker(
                    meeting_id=meeting_id,
                    label=label,
                    color=SPEAKER_COLORS[index % len(SPEAKER_COLORS)],
                )
                db.add(speaker)
                await db.flush()
                existing[label] = speaker
                index += 1
            hint_to_speaker[hint] = speaker

        for hint, speaker in hint_to_speaker.items():
            condition = (
                TranscriptSegment.speaker_hint.is_(None)
                if hint is None
                else TranscriptSegment.speaker_hint == hint
            )
            from sqlalchemy import update

            await db.execute(
                update(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting_id, condition)
                .values(speaker_id=speaker.id)
            )
        await db.commit()


# ── Extracción final (single-pass o jerárquica) ──────────────────


async def _extract_final(provider, lines: list[dict], bookmarks_text: str) -> dict:
    full_text = transcript_to_text(lines)
    if len(full_text) <= SINGLE_PASS_CHAR_LIMIT:
        result = await provider.chat_json(
            FINAL_EXTRACT_SYSTEM,
            [{"role": "user", "content": build_final_extract_prompt(full_text, bookmarks_text)}],
            temperature=0.1,
            max_tokens=8000,
        )
        return result if isinstance(result, dict) else {}

    # Jerárquico: dividir en secciones, extraer por sección y fusionar
    sections = _split_sections(lines, SINGLE_PASS_CHAR_LIMIT)
    merged: dict = {
        "topics": [], "decisions": [], "tasks": [], "questions": [], "risks": [],
        "mentions": {"people": [], "projects": [], "dates": [], "numbers": [], "links": []},
        "timeline": [], "next_steps": [],
    }
    for section_lines in sections:
        section_text = transcript_to_text(section_lines)
        try:
            partial = await provider.chat_json(
                FINAL_EXTRACT_SYSTEM,
                [{"role": "user", "content": build_final_extract_prompt(section_text, bookmarks_text)}],
                temperature=0.1,
                max_tokens=8000,
            )
        except LLMError:
            continue
        if not isinstance(partial, dict):
            continue
        for key in ("topics", "decisions", "tasks", "questions", "risks", "timeline", "next_steps"):
            merged[key].extend(partial.get(key) or [])
        mentions = partial.get("mentions") or {}
        for key in merged["mentions"]:
            merged["mentions"][key].extend(mentions.get(key) or [])

    # dedupe básico por texto
    for key in ("decisions", "tasks", "questions", "risks"):
        seen: set[str] = set()
        unique = []
        for item in merged[key]:
            text = str(item.get("text", "")).strip().lower()
            if text and text not in seen:
                seen.add(text)
                unique.append(item)
        merged[key] = unique
    return merged


def _split_sections(lines: list[dict], char_limit: int) -> list[list[dict]]:
    sections: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for line in lines:
        line_size = len(line["text"]) + 30
        if size + line_size > char_limit and current:
            sections.append(current)
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        sections.append(current)
    return sections


async def _persist_insights(meeting_id: uuid.UUID, insights: dict, reference_date) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id

        # La pasada final reemplaza lo extraído en vivo (consolidado > incremental)
        for model in (MeetingTopic, Decision, Question, Risk):
            await db.execute(delete(model).where(model.meeting_id == meeting_id))
        # Las tareas en vivo pueden tener estado cambiado a mano: solo borrar las "ai" intactas
        await db.execute(
            delete(ActionItem).where(
                ActionItem.meeting_id == meeting_id,
                ActionItem.source == "ai",
                ActionItem.status == "pending",
            )
        )

        for item in insights.get("topics", []) or []:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            db.add(
                MeetingTopic(
                    meeting_id=meeting_id, organization_id=org_id, title=title,
                    summary=item.get("summary"),
                    start_ms=_ms(item.get("start_ms")), end_ms=_ms(item.get("end_ms")),
                )
            )
        for item in insights.get("decisions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Decision(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    context=item.get("context"),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
        participants = (
            (
                await db.execute(
                    select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
        participant_users = {p.name.lower(): p.user_id for p in participants if p.user_id}
        for item in insights.get("tasks", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            assignee = item.get("assignee")
            due_text = item.get("due")
            db.add(
                ActionItem(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    assignee_name=assignee,
                    assignee_user_id=participant_users.get((assignee or "").lower()),
                    due_text=due_text,
                    due_date=resolve_relative_date(due_text, reference_date),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
        for item in insights.get("questions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Question(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
        for item in insights.get("risks", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Risk(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )

        meeting.meta = {
            **(meeting.meta or {}),
            "mentions": insights.get("mentions") or {},
            "timeline": insights.get("timeline") or [],
            "next_steps": insights.get("next_steps") or [],
        }
        await db.commit()


# ── Resúmenes ────────────────────────────────────────────────────


async def _generate_summaries(
    provider, meeting_id: uuid.UUID, org_id: uuid.UUID, language: str, lines: list[dict], insights: dict
) -> None:
    full_text = transcript_to_text(lines)

    if len(full_text) > SINGLE_PASS_CHAR_LIMIT:
        # jerárquico: resumen por sección → resumen global sobre los resúmenes
        section_summaries = []
        for section_lines in _split_sections(lines, SINGLE_PASS_CHAR_LIMIT):
            try:
                partial = await provider.chat_json(
                    SECTION_SUMMARY_SYSTEM,
                    [{"role": "user", "content": build_section_summary_prompt(transcript_to_text(section_lines))}],
                )
                if isinstance(partial, dict) and partial.get("summary"):
                    start = format_ms(section_lines[0]["start_ms"])
                    section_summaries.append(f"[Sección desde {start}] {partial['summary']}")
            except LLMError:
                continue
        source_text = "\n\n".join(section_summaries) or full_text[:SINGLE_PASS_CHAR_LIMIT]
    else:
        source_text = full_text

    insights_compact = json.dumps(
        {
            "decisions": [d.get("text") for d in insights.get("decisions", [])[:20]],
            "tasks": [t.get("text") for t in insights.get("tasks", [])[:20]],
        },
        ensure_ascii=False,
    )
    result = await provider.chat_json(
        SUMMARY_SYSTEM.format(language=language),
        [{"role": "user", "content": build_summary_prompt(source_text, insights_compact)}],
        max_tokens=6000,
    )
    if not isinstance(result, dict):
        return

    async with SessionLocal() as db:
        await db.execute(
            delete(MeetingSummary).where(
                MeetingSummary.meeting_id == meeting_id,
                MeetingSummary.kind.in_(["executive", "detailed"]),
            )
        )
        model_name = getattr(provider, "model", provider.name)
        if result.get("executive"):
            db.add(
                MeetingSummary(
                    meeting_id=meeting_id, organization_id=org_id, kind="executive",
                    content={"points": result["executive"]}, model_used=model_name,
                )
            )
        if result.get("detailed"):
            db.add(
                MeetingSummary(
                    meeting_id=meeting_id, organization_id=org_id, kind="detailed",
                    content={"markdown": result["detailed"]}, model_used=model_name,
                )
            )
        await db.commit()


def _ms(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
