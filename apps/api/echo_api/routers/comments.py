"""Comentarios sobre acta, transcript, decisiones y tareas."""
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context
from ..models import Comment, Notification, OrganizationMember, User
from ..services.audit import audit

router = APIRouter(prefix="/api/comments", tags=["comments"])

TARGET_TYPES = ("minutes_block", "segment", "decision", "action_item", "meeting")


class CommentIn(BaseModel):
    meeting_id: uuid.UUID
    target_type: str
    target_id: str = Field(max_length=80)
    text: str = Field(min_length=1, max_length=4000)


class CommentOut(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID | None
    target_type: str
    target_id: str
    text: str
    author_id: uuid.UUID
    author_name: str
    author_color: str
    resolved_at: datetime | None
    created_at: datetime


async def _resolve_mentions(db: AsyncSession, org_id: uuid.UUID, text: str) -> list[str]:
    """@Nombre → user_ids de la organización."""
    names = re.findall(r"@([\wÁÉÍÓÚáéíóúñÑ]+)", text)
    if not names:
        return []
    rows = (
        await db.execute(
            select(User)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == org_id)
        )
    ).scalars().all()
    mentioned = []
    for user in rows:
        first_name = user.name.split()[0].lower()
        if any(name.lower() == first_name or name.lower() in user.name.lower() for name in names):
            mentioned.append(str(user.id))
    return mentioned


@router.post("", response_model=CommentOut, status_code=201)
async def create_comment(
    data: CommentIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    if data.target_type not in TARGET_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_type inválido")
    meeting = await get_meeting_or_404(data.meeting_id, ctx, db, minimum_role="commenter")
    mentions = await _resolve_mentions(db, ctx.org_id, data.text)
    comment = Comment(
        organization_id=ctx.org_id,
        meeting_id=meeting.id,
        author_id=ctx.user.id,
        target_type=data.target_type,
        target_id=data.target_id,
        text=data.text,
        mentions=mentions or None,
    )
    db.add(comment)
    await db.flush()
    for user_id in mentions:
        if user_id != str(ctx.user.id):
            db.add(
                Notification(
                    user_id=uuid.UUID(user_id),
                    organization_id=ctx.org_id,
                    kind="comment",
                    title=f"{ctx.user.name} te mencionó en «{meeting.title}»",
                    body=data.text[:200],
                    link=f"/meetings/{meeting.id}",
                )
            )
    await audit(db, ctx.org_id, ctx.user.id, "comment.create", data.target_type, data.target_id)
    await db.commit()
    await db.refresh(comment)
    return CommentOut(
        id=comment.id, meeting_id=comment.meeting_id, target_type=comment.target_type,
        target_id=comment.target_id, text=comment.text, author_id=ctx.user.id,
        author_name=ctx.user.name, author_color=ctx.user.avatar_color,
        resolved_at=comment.resolved_at, created_at=comment.created_at,
    )


@router.get("", response_model=list[CommentOut])
async def list_comments(
    meeting_id: uuid.UUID,
    target_type: str | None = None,
    target_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    query = (
        select(Comment, User)
        .join(User, User.id == Comment.author_id)
        .where(
            Comment.meeting_id == meeting.id,
            Comment.organization_id == ctx.org_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at)
    )
    if target_type:
        query = query.where(Comment.target_type == target_type)
    if target_id:
        query = query.where(Comment.target_id == target_id)
    rows = (await db.execute(query)).all()
    return [
        CommentOut(
            id=c.id, meeting_id=c.meeting_id, target_type=c.target_type, target_id=c.target_id,
            text=c.text, author_id=u.id, author_name=u.name, author_color=u.avatar_color,
            resolved_at=c.resolved_at, created_at=c.created_at,
        )
        for c, u in rows
    ]


@router.post("/{comment_id}/resolve", response_model=CommentOut)
async def resolve_comment(
    comment_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    comment = (
        await db.execute(
            select(Comment).where(Comment.id == comment_id, Comment.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not comment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comentario no encontrado")
    comment.resolved_at = datetime.now(UTC)
    comment.resolved_by = ctx.user.id
    await db.commit()
    author = await db.get(User, comment.author_id)
    return CommentOut(
        id=comment.id, meeting_id=comment.meeting_id, target_type=comment.target_type,
        target_id=comment.target_id, text=comment.text, author_id=author.id,
        author_name=author.name, author_color=author.avatar_color,
        resolved_at=comment.resolved_at, created_at=comment.created_at,
    )


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    comment = (
        await db.execute(
            select(Comment).where(Comment.id == comment_id, Comment.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not comment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comentario no encontrado")
    if comment.author_id != ctx.user.id:
        ctx.require_role("admin")
    comment.deleted_at = datetime.now(UTC)
    await db.commit()
