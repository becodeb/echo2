"""Personas de la organización: perfil, reuniones, tareas, intervenciones."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import (
    ActionItem,
    Meeting,
    MeetingParticipant,
    OrganizationMember,
    Speaker,
    TranscriptSegment,
    User,
)

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("")
async def list_people(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    members = (
        await db.execute(
            select(User, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == ctx.org_id)
            .order_by(User.name)
        )
    ).all()
    output = []
    for user, role in members:
        meeting_count = (
            await db.execute(
                select(func.count(MeetingParticipant.id))
                .join(Meeting, Meeting.id == MeetingParticipant.meeting_id)
                .where(
                    Meeting.organization_id == ctx.org_id,
                    (MeetingParticipant.user_id == user.id)
                    | (MeetingParticipant.name.ilike(user.name)),
                )
            )
        ).scalar()
        open_tasks = (
            await db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.organization_id == ctx.org_id,
                    ActionItem.status.in_(["pending", "in_progress"]),
                    (ActionItem.assignee_user_id == user.id)
                    | (ActionItem.assignee_name.ilike(user.name)),
                )
            )
        ).scalar()
        output.append(
            {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "avatar_color": user.avatar_color,
                "job_title": user.job_title,
                "role": role,
                "meeting_count": meeting_count or 0,
                "open_task_count": open_tasks or 0,
            }
        )
    return output


@router.get("/{user_id}")
async def person_detail(
    user_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    member = (
        await db.execute(
            select(User, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(
                OrganizationMember.organization_id == ctx.org_id,
                User.id == user_id,
            )
        )
    ).first()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    user, role = member

    meetings = (
        await db.execute(
            select(Meeting)
            .join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
            .where(
                Meeting.organization_id == ctx.org_id,
                Meeting.deleted_at.is_(None),
                (MeetingParticipant.user_id == user.id)
                | (MeetingParticipant.name.ilike(user.name)),
            )
            .order_by(Meeting.created_at.desc())
            .limit(15)
        )
    ).scalars().all()

    tasks = (
        await db.execute(
            select(ActionItem, Meeting.title)
            .outerjoin(Meeting, Meeting.id == ActionItem.meeting_id)
            .where(
                ActionItem.organization_id == ctx.org_id,
                (ActionItem.assignee_user_id == user.id)
                | (ActionItem.assignee_name.ilike(user.name)),
            )
            .order_by(ActionItem.created_at.desc())
            .limit(20)
        )
    ).all()

    # últimas intervenciones: segmentos de speakers con su nombre
    interventions = (
        await db.execute(
            select(TranscriptSegment, Meeting.title, Meeting.id)
            .join(Speaker, Speaker.id == TranscriptSegment.speaker_id)
            .join(Meeting, Meeting.id == TranscriptSegment.meeting_id)
            .where(
                TranscriptSegment.organization_id == ctx.org_id,
                Speaker.display_name.ilike(user.name.split()[0] + "%"),
            )
            .order_by(TranscriptSegment.created_at.desc())
            .limit(10)
        )
    ).all()

    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "avatar_color": user.avatar_color,
        "job_title": user.job_title,
        "role": role,
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "started_at": m.started_at.isoformat() if m.started_at else None,
            }
            for m in meetings
        ],
        "tasks": [
            {
                "id": str(t.id),
                "text": t.text,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "meeting_title": title,
            }
            for t, title in tasks
        ],
        "interventions": [
            {
                "meeting_id": str(meeting_id),
                "meeting_title": title,
                "start_ms": segment.start_ms,
                "text": segment.text[:200],
            }
            for segment, title, meeting_id in interventions
        ],
    }
