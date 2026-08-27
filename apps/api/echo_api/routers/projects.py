"""Proyectos: CRUD, asociación de reuniones, timeline y 'qué cambió'."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context
from ..models import (
    ActionItem,
    Decision,
    Meeting,
    MeetingParticipant,
    Project,
    ProjectMeeting,
    Question,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    color: str = Field(default="#6366f1", max_length=16)


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    color: str
    meeting_count: int = 0
    decision_count: int = 0
    open_task_count: int = 0
    last_meeting_at: datetime | None = None


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("member")
    project = Project(
        organization_id=ctx.org_id, name=data.name.strip(),
        description=data.description, color=data.color,
    )
    db.add(project)
    await audit(db, ctx.org_id, ctx.user.id, "project.create", "project", data.name)
    await db.commit()
    await db.refresh(project)
    return ProjectOut(
        id=project.id, name=project.name, description=project.description,
        status=project.status, color=project.color,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    projects = (
        (
            await db.execute(
                select(Project)
                .where(Project.organization_id == ctx.org_id, Project.deleted_at.is_(None))
                .order_by(Project.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    output = []
    for project in projects:
        meeting_ids = (
            (
                await db.execute(
                    select(ProjectMeeting.meeting_id).where(ProjectMeeting.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        meeting_count = len(meeting_ids)
        decision_count = 0
        open_tasks = 0
        last_meeting = None
        if meeting_ids:
            decision_count = (
                await db.execute(
                    select(func.count(Decision.id)).where(Decision.meeting_id.in_(meeting_ids))
                )
            ).scalar()
            open_tasks = (
                await db.execute(
                    select(func.count(ActionItem.id)).where(
                        ActionItem.meeting_id.in_(meeting_ids),
                        ActionItem.status.in_(["pending", "in_progress"]),
                    )
                )
            ).scalar()
            last_meeting = (
                await db.execute(
                    select(func.max(Meeting.started_at)).where(Meeting.id.in_(meeting_ids))
                )
            ).scalar()
        output.append(
            ProjectOut(
                id=project.id, name=project.name, description=project.description,
                status=project.status, color=project.color,
                meeting_count=meeting_count, decision_count=decision_count or 0,
                open_task_count=open_tasks or 0, last_meeting_at=last_meeting,
            )
        )
    return output


@router.get("/{project_id}")
async def project_detail(
    project_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == ctx.org_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")

    meeting_ids = (
        (
            await db.execute(
                select(ProjectMeeting.meeting_id).where(ProjectMeeting.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    meetings = []
    if meeting_ids:
        rows = (
            await db.execute(
                select(Meeting, func.count(MeetingParticipant.id))
                .outerjoin(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
                .where(Meeting.id.in_(meeting_ids), Meeting.deleted_at.is_(None))
                .group_by(Meeting.id)
                .order_by(Meeting.created_at.desc())
            )
        ).all()
        meetings = [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "duration_seconds": m.duration_seconds,
                "participant_count": count,
            }
            for m, count in rows
        ]

    # Timeline del proyecto: creación + reuniones + decisiones
    timeline: list[dict] = [
        {"at": project.created_at.isoformat(), "kind": "project_created", "label": "Proyecto creado"}
    ]
    if meeting_ids:
        decision_rows = (
            await db.execute(
                select(Decision, Meeting.title)
                .join(Meeting, Meeting.id == Decision.meeting_id)
                .where(Decision.meeting_id.in_(meeting_ids))
                .order_by(Decision.created_at)
            )
        ).all()
        for decision, meeting_title in decision_rows:
            timeline.append(
                {
                    "at": decision.created_at.isoformat(),
                    "kind": "decision",
                    "label": decision.text[:140],
                    "meeting_id": str(decision.meeting_id),
                    "meeting_title": meeting_title,
                    "evidence_start_ms": decision.evidence_start_ms,
                }
            )
        for meeting_row in meetings:
            if meeting_row["started_at"]:
                timeline.append(
                    {
                        "at": meeting_row["started_at"],
                        "kind": "meeting",
                        "label": meeting_row["title"],
                        "meeting_id": meeting_row["id"],
                    }
                )
    timeline.sort(key=lambda item: item["at"])

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "color": project.color,
        "meetings": meetings,
        "timeline": timeline,
    }


@router.get("/{project_id}/changes")
async def project_changes(
    project_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """«¿Qué cambió desde la última reunión?»: compara las dos últimas reuniones."""
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")

    meetings = (
        (
            await db.execute(
                select(Meeting)
                .join(ProjectMeeting, ProjectMeeting.meeting_id == Meeting.id)
                .where(
                    ProjectMeeting.project_id == project.id,
                    Meeting.status == "completed",
                    Meeting.deleted_at.is_(None),
                )
                .order_by(Meeting.started_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(meetings) < 2:
        return {"has_comparison": False, "message": "Se necesitan al menos dos reuniones completadas"}

    latest, previous = meetings[0], meetings[1]

    async def snapshot(meeting: Meeting) -> dict:
        decisions = (
            (await db.execute(select(Decision).where(Decision.meeting_id == meeting.id)))
            .scalars()
            .all()
        )
        tasks = (
            (await db.execute(select(ActionItem).where(ActionItem.meeting_id == meeting.id)))
            .scalars()
            .all()
        )
        questions = (
            (await db.execute(select(Question).where(Question.meeting_id == meeting.id)))
            .scalars()
            .all()
        )
        return {
            "meeting_id": str(meeting.id),
            "title": meeting.title,
            "date": meeting.started_at.isoformat() if meeting.started_at else None,
            "decisions": [
                {"text": d.text, "evidence_start_ms": d.evidence_start_ms} for d in decisions
            ],
            "tasks": [
                {"text": t.text, "assignee": t.assignee_name, "status": t.status} for t in tasks
            ],
            "open_questions": [q.text for q in questions if not q.resolved],
        }

    return {
        "has_comparison": True,
        "before": await snapshot(previous),
        "after": await snapshot(latest),
    }


class LinkMeetingIn(BaseModel):
    meeting_id: uuid.UUID


@router.post("/{project_id}/meetings", status_code=201)
async def link_meeting(
    project_id: uuid.UUID,
    data: LinkMeetingIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")
    meeting = await get_meeting_or_404(data.meeting_id, ctx, db)
    existing = (
        await db.execute(
            select(ProjectMeeting).where(
                ProjectMeeting.project_id == project.id, ProjectMeeting.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(ProjectMeeting(project_id=project.id, meeting_id=meeting.id))
        await db.commit()
    return {"ok": True}


@router.delete("/{project_id}/meetings/{meeting_id}", status_code=204)
async def unlink_meeting(
    project_id: uuid.UUID,
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")
    await db.execute(
        delete(ProjectMeeting).where(
            ProjectMeeting.project_id == project.id, ProjectMeeting.meeting_id == meeting_id
        )
    )
    await db.commit()
