"""Compartir reuniones: por persona, por organización o por link."""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import (
    Meeting,
    MeetingShare,
    MeetingSummary,
    Minutes,
    MinutesVersion,
    Notification,
    SharedLink,
    Speaker,
    TranscriptSegment,
    User,
)
from ..services.audit import audit

router = APIRouter(tags=["sharing"])

SHARE_ROLES = ("viewer", "commenter", "editor", "admin")


class ShareUserIn(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="viewer")


@router.get("/api/meetings/{meeting_id}/shares")
async def list_shares(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    shares = (
        await db.execute(
            select(MeetingShare, User)
            .join(User, User.id == MeetingShare.user_id)
            .where(MeetingShare.meeting_id == meeting.id)
        )
    ).all()
    links = (
        (
            await db.execute(
                select(SharedLink).where(
                    SharedLink.meeting_id == meeting.id, SharedLink.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "visibility": (meeting.meta or {}).get("visibility", "org"),
        "users": [
            {"id": str(s.id), "user_id": str(u.id), "name": u.name, "email": u.email, "role": s.role}
            for s, u in shares
        ],
        "links": [
            {
                "id": str(l.id),
                "token": l.token,
                "role": l.role,
                "expires_at": l.expires_at.isoformat() if l.expires_at else None,
                "allow_download": l.allow_download,
                "access_count": l.access_count,
            }
            for l in links
        ],
    }


@router.post("/api/meetings/{meeting_id}/shares", status_code=201)
async def share_with_user(
    meeting_id: uuid.UUID,
    data: ShareUserIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    if data.role not in SHARE_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rol inválido")
    target = await db.get(User, data.user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    existing = (
        await db.execute(
            select(MeetingShare).where(
                MeetingShare.meeting_id == meeting.id, MeetingShare.user_id == data.user_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.role = data.role
    else:
        db.add(
            MeetingShare(
                meeting_id=meeting.id, user_id=data.user_id, role=data.role, granted_by=ctx.user.id
            )
        )
        db.add(
            Notification(
                user_id=data.user_id,
                organization_id=ctx.org_id,
                kind="meeting_shared",
                title=f"{ctx.user.name} compartió «{meeting.title}» con vos",
                link=f"/meetings/{meeting.id}",
            )
        )
    await audit(db, ctx.org_id, ctx.user.id, "meeting.share", "meeting", str(meeting.id),
                detail={"user_id": str(data.user_id), "role": data.role})
    await db.commit()
    return {"ok": True}


@router.delete("/api/meetings/{meeting_id}/shares/{share_id}", status_code=204)
async def revoke_share(
    meeting_id: uuid.UUID,
    share_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    share = (
        await db.execute(
            select(MeetingShare).where(
                MeetingShare.id == share_id, MeetingShare.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if share:
        await db.delete(share)
        await db.commit()


class ShareLinkIn(BaseModel):
    role: str = Field(default="viewer", pattern="^(viewer|commenter)$")
    expires_days: int | None = Field(default=None, ge=1, le=365)
    allow_download: bool = True


@router.post("/api/meetings/{meeting_id}/share-links", status_code=201)
async def create_share_link(
    meeting_id: uuid.UUID,
    data: ShareLinkIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    link = SharedLink(
        meeting_id=meeting.id,
        organization_id=ctx.org_id,
        token=secrets.token_urlsafe(32),
        role=data.role,
        created_by=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=data.expires_days) if data.expires_days else None,
        allow_download=data.allow_download,
    )
    db.add(link)
    await audit(db, ctx.org_id, ctx.user.id, "meeting.share_link_created", "meeting", str(meeting.id))
    await db.commit()
    await db.refresh(link)
    return {"token": link.token, "role": link.role}


@router.delete("/api/meetings/{meeting_id}/share-links/{link_id}", status_code=204)
async def revoke_share_link(
    meeting_id: uuid.UUID,
    link_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    link = (
        await db.execute(
            select(SharedLink).where(SharedLink.id == link_id, SharedLink.meeting_id == meeting.id)
        )
    ).scalar_one_or_none()
    if link:
        link.revoked_at = datetime.now(UTC)
        await audit(db, ctx.org_id, ctx.user.id, "meeting.share_link_revoked", "meeting", str(meeting.id))
        await db.commit()


# ── Vista pública por link (sin autenticación) ───────────────────


@router.get("/api/shared/{token}")
async def view_shared_meeting(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    link = (
        await db.execute(select(SharedLink).where(SharedLink.token == token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if not link or link.revoked_at is not None or (link.expires_at and link.expires_at < now):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link inválido o expirado")

    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == link.meeting_id, Meeting.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not meeting:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión no encontrada")

    link.access_count += 1
    db.add(link)

    segments = (
        (
            await db.execute(
                select(TranscriptSegment, Speaker)
                .outerjoin(Speaker, Speaker.id == TranscriptSegment.speaker_id)
                .where(
                    TranscriptSegment.meeting_id == meeting.id,
                    TranscriptSegment.is_final.is_(True),
                )
                .order_by(TranscriptSegment.seq)
                .limit(3000)
            )
        )
    ).all()

    minutes_markdown = None
    minutes = (
        await db.execute(select(Minutes).where(Minutes.meeting_id == meeting.id))
    ).scalar_one_or_none()
    if minutes:
        version = (
            await db.execute(
                select(MinutesVersion).where(
                    MinutesVersion.minutes_id == minutes.id,
                    MinutesVersion.version == minutes.current_version,
                )
            )
        ).scalar_one_or_none()
        minutes_markdown = version.body_markdown if version else None

    summary = (
        await db.execute(
            select(MeetingSummary).where(
                MeetingSummary.meeting_id == meeting.id, MeetingSummary.kind == "executive"
            )
        )
    ).scalar_one_or_none()

    await db.commit()
    return {
        "meeting": {
            "title": meeting.title,
            "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
            "duration_seconds": meeting.duration_seconds,
        },
        "role": link.role,
        "allow_download": link.allow_download,
        "executive_summary": summary.content if summary else None,
        "minutes_markdown": minutes_markdown,
        "transcript": [
            {
                "seq": s.seq,
                "start_ms": s.start_ms,
                "speaker": (sp.display_name or sp.label) if sp else None,
                "text": s.text,
            }
            for s, sp in segments
        ],
    }
