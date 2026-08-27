"""Tareas (action items como objetos reales) + panel «Mi trabajo» + follow-up."""
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import (
    ActionItem,
    Comment,
    Meeting,
    Notification,
    OrganizationMember,
    User,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

TASK_STATUS = ("pending", "in_progress", "done", "cancelled")


class TaskOut(BaseModel):
    id: uuid.UUID
    text: str
    assignee_name: str | None
    assignee_user_id: uuid.UUID | None
    due_text: str | None
    due_date: date | None
    status: str
    source: str
    meeting_id: uuid.UUID | None
    meeting_title: str | None = None
    evidence_start_ms: int | None
    overdue: bool = False
    created_at: datetime


def _task_out(task: ActionItem, meeting_title: str | None) -> TaskOut:
    overdue = bool(
        task.due_date
        and task.status in ("pending", "in_progress")
        and task.due_date < datetime.now(UTC).date()
    )
    return TaskOut(
        id=task.id,
        text=task.text,
        assignee_name=task.assignee_name,
        assignee_user_id=task.assignee_user_id,
        due_text=task.due_text,
        due_date=task.due_date,
        status=task.status,
        source=task.source,
        meeting_id=task.meeting_id,
        meeting_title=meeting_title,
        evidence_start_ms=task.evidence_start_ms,
        overdue=overdue,
        created_at=task.created_at,
    )


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    assignee: str | None = None,
    mine: bool = False,
    limit: int = Query(default=100, le=300),
):
    query = (
        select(ActionItem, Meeting.title)
        .outerjoin(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(ActionItem.organization_id == ctx.org_id)
        .order_by(ActionItem.due_date.asc().nullslast(), ActionItem.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(ActionItem.status == status_filter)
    if assignee:
        query = query.where(ActionItem.assignee_name.ilike(f"%{assignee}%"))
    if mine:
        query = query.where(
            (ActionItem.assignee_user_id == ctx.user.id)
            | (ActionItem.assignee_name.ilike(f"%{ctx.user.name}%"))
        )
    rows = (await db.execute(query)).all()
    return [_task_out(task, title) for task, title in rows]


class TaskUpdateIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(pending|in_progress|done|cancelled)$")
    text: str | None = Field(default=None, max_length=2000)
    assignee_user_id: uuid.UUID | None = None
    assignee_name: str | None = Field(default=None, max_length=200)
    due_date: date | None = None


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdateIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.id == task_id, ActionItem.organization_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarea no encontrada")

    if data.status and data.status != task.status:
        task.status = data.status
    if data.text:
        task.text = data.text.strip()
        task.source = "manual" if task.source == "ai" else task.source
    if data.due_date is not None:
        task.due_date = data.due_date
    if data.assignee_name is not None:
        task.assignee_name = data.assignee_name or None
    if data.assignee_user_id is not None:
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == ctx.org_id,
                    OrganizationMember.user_id == data.assignee_user_id,
                )
            )
        ).scalar_one_or_none()
        if not member:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "El usuario no pertenece a la organización")
        task.assignee_user_id = data.assignee_user_id
        assignee_user = await db.get(User, data.assignee_user_id)
        if assignee_user:
            if not task.assignee_name:
                task.assignee_name = assignee_user.name
            if assignee_user.id != ctx.user.id:
                db.add(
                    Notification(
                        user_id=assignee_user.id,
                        organization_id=ctx.org_id,
                        kind="task_assigned",
                        title=f"{ctx.user.name} te asignó una tarea",
                        body=task.text[:200],
                        link=f"/tasks",
                    )
                )
    await audit(db, ctx.org_id, ctx.user.id, "task.update", "task", str(task.id))
    await db.commit()
    await db.refresh(task)
    meeting_title = None
    if task.meeting_id:
        meeting = await db.get(Meeting, task.meeting_id)
        meeting_title = meeting.title if meeting else None
    return _task_out(task, meeting_title)


class TaskCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    assignee_name: str | None = None
    due_date: date | None = None
    meeting_id: uuid.UUID | None = None


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    data: TaskCreateIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    meeting_title = None
    if data.meeting_id:
        meeting = (
            await db.execute(
                select(Meeting).where(
                    Meeting.id == data.meeting_id, Meeting.organization_id == ctx.org_id
                )
            )
        ).scalar_one_or_none()
        if not meeting:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión no encontrada")
        meeting_title = meeting.title
    task = ActionItem(
        organization_id=ctx.org_id,
        meeting_id=data.meeting_id,
        text=data.text.strip(),
        assignee_name=data.assignee_name,
        due_date=data.due_date,
        source="manual",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_out(task, meeting_title)


# ── Panel «Mi trabajo» ───────────────────────────────────────────


@router.get("/my-work")
async def my_work(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    today = datetime.now(UTC).date()

    tasks_rows = (
        await db.execute(
            select(ActionItem, Meeting.title)
            .outerjoin(Meeting, Meeting.id == ActionItem.meeting_id)
            .where(
                ActionItem.organization_id == ctx.org_id,
                ActionItem.status.in_(["pending", "in_progress"]),
                (ActionItem.assignee_user_id == ctx.user.id)
                | (ActionItem.assignee_name.ilike(f"%{ctx.user.name}%")),
            )
            .order_by(ActionItem.due_date.asc().nullslast())
            .limit(50)
        )
    ).all()

    recent_meetings = (
        (
            await db.execute(
                select(Meeting)
                .where(
                    Meeting.organization_id == ctx.org_id,
                    Meeting.deleted_at.is_(None),
                    Meeting.status == "completed",
                )
                .order_by(Meeting.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    mentions = (
        (
            await db.execute(
                select(Comment)
                .where(
                    Comment.organization_id == ctx.org_id,
                    Comment.deleted_at.is_(None),
                    Comment.mentions.contains([str(ctx.user.id)]),
                    Comment.resolved_at.is_(None),
                )
                .order_by(Comment.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    # Follow-up: tareas aparentemente vencidas (NUNCA se cambia el estado solas)
    overdue = [
        {"id": str(t.id), "text": t.text, "due_date": t.due_date.isoformat(), "meeting_title": title}
        for t, title in tasks_rows
        if t.due_date and t.due_date < today
    ]

    return {
        "tasks": [
            _task_out(task, title).model_dump(mode="json") for task, title in tasks_rows
        ],
        "overdue_suggestions": overdue,
        "recent_meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "duration_seconds": m.duration_seconds,
            }
            for m in recent_meetings
        ],
        "mentions": [
            {
                "id": str(c.id),
                "text": c.text[:200],
                "meeting_id": str(c.meeting_id) if c.meeting_id else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in mentions
        ],
    }
