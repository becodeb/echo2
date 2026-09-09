"""Enlaces adjuntos a una reunión.

Echo guarda la URL y nada más: no descarga, no copia y no indexa el contenido.
El material sensible sigue viviendo donde la institución ya lo tiene, que es
coherente con que Echo tampoco guarde el audio.
"""
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import MeetingAttachment

router = APIRouter(tags=["attachments"])

# Solo http(s). Sin esto entran javascript: y data:, que convierten cada
# adjunto en un XSS con un clic.
ALLOWED_SCHEMES = ("http", "https")


class AttachmentOut(BaseModel):
    id: uuid.UUID
    url: str
    title: str | None

    class Config:
        from_attributes = True


class AttachmentIn(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    title: str | None = Field(default=None, max_length=200)


def _clean_url(raw: str) -> str:
    url = raw.strip()
    # Un pegado típico viene sin esquema; asumir https es más útil que
    # rechazarlo, y sigue quedando dentro de la lista permitida.
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El enlace tiene que empezar con http o https")
    return url


@router.get("/api/meetings/{meeting_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    rows = (
        (
            await db.execute(
                select(MeetingAttachment)
                .where(MeetingAttachment.meeting_id == meeting.id)
                .order_by(MeetingAttachment.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [AttachmentOut.model_validate(row) for row in rows]


@router.post("/api/meetings/{meeting_id}/attachments", response_model=AttachmentOut, status_code=201)
async def add_attachment(
    meeting_id: uuid.UUID,
    data: AttachmentIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    attachment = MeetingAttachment(
        meeting_id=meeting.id,
        url=_clean_url(data.url),
        title=(data.title or "").strip() or None,
        added_by=ctx.user.id,
    )
    db.add(attachment)
    await db.flush()
    await db.commit()
    return AttachmentOut.model_validate(attachment)


@router.delete("/api/meetings/{meeting_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    meeting_id: uuid.UUID,
    attachment_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    row = (
        await db.execute(
            select(MeetingAttachment).where(
                MeetingAttachment.id == attachment_id,
                MeetingAttachment.meeting_id == meeting.id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
