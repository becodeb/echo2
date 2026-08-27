"""Memoria organizacional: explorar entidades y sus hechos + dashboard + prep."""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context
from ..models import (
    ActionItem,
    Decision,
    Meeting,
    MeetingLink,
    MemoryEntity,
    MemoryRelation,
    Project,
    ProjectMeeting,
    Question,
)

router = APIRouter(tags=["memory"])


@router.get("/api/memory/entities")
async def list_entities(
    kind: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(MemoryEntity, func.count(MemoryRelation.id))
        .outerjoin(MemoryRelation, MemoryRelation.entity_id == MemoryEntity.id)
        .where(
            MemoryEntity.organization_id == ctx.org_id,
            MemoryEntity.deleted_at.is_(None),
        )
        .group_by(MemoryEntity.id)
        .order_by(func.count(MemoryRelation.id).desc())
        .limit(100)
    )
    if kind:
        query = query.where(MemoryEntity.kind == kind)
    rows = (await db.execute(query)).all()
    return [
        {
            "id": str(entity.id),
            "kind": entity.kind,
            "name": entity.name,
            "summary": entity.summary,
            "fact_count": count,
        }
        for entity, count in rows
    ]


@router.get("/api/memory/entities/{entity_id}")
async def entity_detail(
    entity_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    entity = (
        await db.execute(
            select(MemoryEntity).where(
                MemoryEntity.id == entity_id, MemoryEntity.organization_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if not entity:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entidad no encontrada")
    relations = (
        await db.execute(
            select(MemoryRelation, Meeting)
            .outerjoin(Meeting, Meeting.id == MemoryRelation.meeting_id)
            .where(MemoryRelation.entity_id == entity.id)
            .order_by(MemoryRelation.happened_at.asc().nullslast())
        )
    ).all()
    return {
        "id": str(entity.id),
        "kind": entity.kind,
        "name": entity.name,
        "summary": entity.summary,
        "facts": [
            {
                "relation": relation.relation,
                "fact": relation.fact,
                "meeting_id": str(relation.meeting_id) if relation.meeting_id else None,
                "meeting_title": meeting.title if meeting else None,
                "date": relation.happened_at.isoformat() if relation.happened_at else None,
                "evidence_start_ms": relation.evidence_start_ms,
            }
            for relation, meeting in relations
        ],
    }


# ── Reuniones relacionadas (sugerencias + confirmación) ──────────


@router.get("/api/meetings/{meeting_id}/related")
async def related_meetings(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    links = (
        await db.execute(
            select(MeetingLink, Meeting)
            .join(Meeting, Meeting.id == MeetingLink.related_meeting_id)
            .where(MeetingLink.meeting_id == meeting.id, Meeting.deleted_at.is_(None))
        )
    ).all()
    return [
        {
            "id": str(link.id),
            "meeting_id": str(related.id),
            "title": related.title,
            "started_at": related.started_at.isoformat() if related.started_at else None,
            "kind": link.kind,
            "confirmed": link.confirmed,
            "suggested_reason": link.suggested_reason,
        }
        for link, related in links
    ]


@router.post("/api/meetings/{meeting_id}/related/{link_id}/confirm")
async def confirm_related(
    meeting_id: uuid.UUID,
    link_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    link = (
        await db.execute(
            select(MeetingLink).where(MeetingLink.id == link_id, MeetingLink.meeting_id == meeting.id)
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relación no encontrada")
    link.confirmed = True
    await db.commit()
    return {"ok": True}


@router.delete("/api/meetings/{meeting_id}/related/{link_id}", status_code=204)
async def reject_related(
    meeting_id: uuid.UUID,
    link_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    link = (
        await db.execute(
            select(MeetingLink).where(MeetingLink.id == link_id, MeetingLink.meeting_id == meeting.id)
        )
    ).scalar_one_or_none()
    if link:
        await db.delete(link)
        await db.commit()


# ── Preparar próxima reunión ─────────────────────────────────────


@router.get("/api/prepare-meeting")
async def prepare_meeting(
    project_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Desde la reunión anterior: tareas pendientes, preguntas abiertas y
    decisiones recientes → agenda sugerida."""
    meeting_filter = [Meeting.organization_id == ctx.org_id, Meeting.status == "completed",
                      Meeting.deleted_at.is_(None)]
    query = select(Meeting).where(*meeting_filter).order_by(Meeting.started_at.desc()).limit(1)
    if project_id:
        query = (
            select(Meeting)
            .join(ProjectMeeting, ProjectMeeting.meeting_id == Meeting.id)
            .where(*meeting_filter, ProjectMeeting.project_id == project_id)
            .order_by(Meeting.started_at.desc())
            .limit(1)
        )
    last_meeting = (await db.execute(query)).scalar_one_or_none()
    if not last_meeting:
        return {"has_previous": False}

    pending_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.meeting_id == last_meeting.id,
                ActionItem.status.in_(["pending", "in_progress"]),
            )
        )
    ).scalars().all()
    open_questions = (
        await db.execute(
            select(Question).where(Question.meeting_id == last_meeting.id, Question.resolved.is_(False))
        )
    ).scalars().all()
    recent_decisions = (
        await db.execute(
            select(Decision).where(Decision.meeting_id == last_meeting.id).limit(5)
        )
    ).scalars().all()

    agenda = []
    if pending_tasks:
        agenda.append("Seguimiento de tareas pendientes:")
        agenda.extend(f"  · {t.text} ({t.assignee_name or 'sin responsable'})" for t in pending_tasks[:6])
    if open_questions:
        agenda.append("Preguntas abiertas de la reunión anterior:")
        agenda.extend(f"  · {q.text}" for q in open_questions[:5])
    if recent_decisions:
        agenda.append("Decisiones que requieren seguimiento:")
        agenda.extend(f"  · {d.text}" for d in recent_decisions[:4])

    return {
        "has_previous": True,
        "previous_meeting": {
            "id": str(last_meeting.id),
            "title": last_meeting.title,
            "started_at": last_meeting.started_at.isoformat() if last_meeting.started_at else None,
        },
        "pending_tasks": [
            {"id": str(t.id), "text": t.text, "assignee_name": t.assignee_name} for t in pending_tasks
        ],
        "open_questions": [{"id": str(q.id), "text": q.text} for q in open_questions],
        "decisions_to_follow": [{"id": str(d.id), "text": d.text} for d in recent_decisions],
        "suggested_agenda": agenda,
    }


# ── Dashboard ────────────────────────────────────────────────────


@router.get("/api/dashboard")
async def dashboard(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    recent_meetings = (
        await db.execute(
            select(Meeting)
            .where(Meeting.organization_id == ctx.org_id, Meeting.deleted_at.is_(None))
            .order_by(Meeting.created_at.desc())
            .limit(6)
        )
    ).scalars().all()

    pending_tasks_count = (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.organization_id == ctx.org_id,
                ActionItem.status.in_(["pending", "in_progress"]),
            )
        )
    ).scalar()

    recent_decisions = (
        await db.execute(
            select(Decision, Meeting.title)
            .join(Meeting, Meeting.id == Decision.meeting_id)
            .where(Decision.organization_id == ctx.org_id, Decision.created_at >= week_ago)
            .order_by(Decision.created_at.desc())
            .limit(5)
        )
    ).all()

    active_projects = (
        await db.execute(
            select(Project)
            .where(
                Project.organization_id == ctx.org_id,
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
            .limit(6)
        )
    ).scalars().all()

    my_tasks = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.organization_id == ctx.org_id,
                ActionItem.status.in_(["pending", "in_progress"]),
                (ActionItem.assignee_user_id == ctx.user.id)
                | (ActionItem.assignee_name.ilike(f"%{ctx.user.name.split()[0]}%")),
            )
            .order_by(ActionItem.due_date.asc().nullslast())
            .limit(5)
        )
    ).scalars().all()

    return {
        "greeting_name": ctx.user.name.split()[0],
        "pending_task_count": pending_tasks_count or 0,
        "recent_meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "created_at": m.created_at.isoformat(),
                "duration_seconds": m.duration_seconds,
            }
            for m in recent_meetings
        ],
        "recent_decisions": [
            {
                "id": str(d.id),
                "text": d.text,
                "meeting_id": str(d.meeting_id),
                "meeting_title": title,
            }
            for d, title in recent_decisions
        ],
        "active_projects": [
            {"id": str(p.id), "name": p.name, "color": p.color} for p in active_projects
        ],
        "my_tasks": [
            {
                "id": str(t.id),
                "text": t.text,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "overdue": bool(t.due_date and t.due_date < now.date()),
            }
            for t in my_tasks
        ],
    }
