"""Buscador global: reuniones, transcript (keyword + semántico), personas,
decisiones, tareas y proyectos."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import (
    ActionItem,
    Decision,
    Meeting,
    OrganizationMember,
    Project,
    User,
)
from ..services.ai_settings import resolve_embeddings
from ..services.rag import retrieve_context

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def global_search(
    q: str = Query(min_length=1, max_length=300),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    like = f"%{q}%"

    meetings = (
        (
            await db.execute(
                select(Meeting)
                .where(
                    Meeting.organization_id == ctx.org_id,
                    Meeting.deleted_at.is_(None),
                    Meeting.title.ilike(like),
                )
                .order_by(Meeting.created_at.desc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )

    people = (
        await db.execute(
            select(User)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == ctx.org_id, User.name.ilike(like))
            .limit(6)
        )
    ).scalars().all()

    decisions = (
        (
            await db.execute(
                select(Decision, Meeting.title)
                .join(Meeting, Meeting.id == Decision.meeting_id)
                .where(Decision.organization_id == ctx.org_id, Decision.text.ilike(like))
                .order_by(Decision.created_at.desc())
                .limit(8)
            )
        )
    ).all()

    tasks = (
        (
            await db.execute(
                select(ActionItem, Meeting.title)
                .outerjoin(Meeting, Meeting.id == ActionItem.meeting_id)
                .where(ActionItem.organization_id == ctx.org_id, ActionItem.text.ilike(like))
                .order_by(ActionItem.created_at.desc())
                .limit(8)
            )
        )
    ).all()

    projects = (
        (
            await db.execute(
                select(Project)
                .where(
                    Project.organization_id == ctx.org_id,
                    Project.deleted_at.is_(None),
                    Project.name.ilike(like),
                )
                .limit(6)
            )
        )
        .scalars()
        .all()
    )

    # Transcript: semántico (si hay embeddings) + full-text.
    # «problema impresoras» encuentra «las máquinas no están pudiendo imprimir».
    embeddings_config = await resolve_embeddings(db, ctx.org_id)
    transcript_hits = await retrieve_context(db, ctx.org_id, q, embeddings_config, limit=10)

    return {
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "started_at": m.started_at.isoformat() if m.started_at else None,
            }
            for m in meetings
        ],
        "people": [
            {"id": str(u.id), "name": u.name, "avatar_color": u.avatar_color} for u in people
        ],
        "decisions": [
            {
                "id": str(d.id),
                "text": d.text,
                "meeting_id": str(d.meeting_id),
                "meeting_title": title,
                "evidence_start_ms": d.evidence_start_ms,
            }
            for d, title in decisions
        ],
        "tasks": [
            {
                "id": str(t.id),
                "text": t.text,
                "status": t.status,
                "assignee_name": t.assignee_name,
                "meeting_title": title,
            }
            for t, title in tasks
        ],
        "projects": [
            {"id": str(p.id), "name": p.name, "color": p.color} for p in projects
        ],
        "transcript": [
            {
                "meeting_id": hit["meeting_id"],
                "meeting_title": hit["meeting_title"],
                "start_ms": hit["start_ms"],
                "text": hit["text"][:240],
                "speaker": hit.get("speaker"),
                "semantic": embeddings_config is not None,
            }
            for hit in transcript_hits
        ],
        "semantic_enabled": embeddings_config is not None,
    }
