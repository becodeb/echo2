"""Lectura y edición del transcript + gestión de hablantes."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import SegmentRevision, Speaker, TranscriptSegment
from ..services.audit import audit

router = APIRouter(prefix="/api/meetings/{meeting_id}", tags=["transcript"])


class SegmentOut(BaseModel):
    id: uuid.UUID
    seq: int
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None
    speaker_id: uuid.UUID | None
    edited: bool


class TranscriptPage(BaseModel):
    segments: list[SegmentOut]
    total: int
    next_after: int | None


@router.get("/transcript", response_model=TranscriptPage)
async def get_transcript(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, le=500),
    search: str | None = None,
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    base = select(TranscriptSegment).where(
        TranscriptSegment.meeting_id == meeting.id,
        TranscriptSegment.is_final.is_(True),
    )
    if search:
        base = base.where(TranscriptSegment.text.ilike(f"%{search}%"))
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar()
    rows = (
        (
            await db.execute(
                base.where(TranscriptSegment.seq > after_seq)
                .order_by(TranscriptSegment.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    next_after = rows[-1].seq if len(rows) == limit else None
    return TranscriptPage(
        segments=[
            SegmentOut(
                id=s.id, seq=s.seq, start_ms=s.start_ms, end_ms=s.end_ms, text=s.text,
                confidence=s.confidence, speaker_id=s.speaker_id, edited=s.edited,
            )
            for s in rows
        ],
        total=total or 0,
        next_after=next_after,
    )


class SegmentEditIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.patch("/transcript/{segment_id}", response_model=SegmentOut)
async def edit_segment(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    data: SegmentEditIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    segment = (
        await db.execute(
            select(TranscriptSegment).where(
                TranscriptSegment.id == segment_id, TranscriptSegment.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if not segment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento no encontrado")

    new_text = data.text.strip()
    if new_text != segment.text:
        db.add(
            SegmentRevision(
                segment_id=segment.id,
                previous_text=segment.text,
                new_text=new_text,
                edited_by=ctx.user.id,
            )
        )
        segment.text = new_text
        segment.edited = True
        segment.embedding = None  # se recalcula en el próximo pase de embeddings
        await audit(db, ctx.org_id, ctx.user.id, "transcript.edit", "segment", str(segment.id))
        await db.commit()
        await db.refresh(segment)
    return SegmentOut(
        id=segment.id, seq=segment.seq, start_ms=segment.start_ms, end_ms=segment.end_ms,
        text=segment.text, confidence=segment.confidence, speaker_id=segment.speaker_id,
        edited=segment.edited,
    )


@router.get("/transcript/{segment_id}/history")
async def segment_history(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    segment = (
        await db.execute(
            select(TranscriptSegment).where(
                TranscriptSegment.id == segment_id, TranscriptSegment.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if not segment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento no encontrado")
    rows = (
        (
            await db.execute(
                select(SegmentRevision)
                .where(SegmentRevision.segment_id == segment_id)
                .order_by(SegmentRevision.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "previous_text": r.previous_text,
            "new_text": r.new_text,
            "edited_by": str(r.edited_by),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ── Hablantes ────────────────────────────────────────────────────


class SpeakerRenameIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


@router.patch("/speakers/{speaker_id}")
async def rename_speaker(
    meeting_id: uuid.UUID,
    speaker_id: uuid.UUID,
    data: SpeakerRenameIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    speaker = (
        await db.execute(
            select(Speaker).where(Speaker.id == speaker_id, Speaker.meeting_id == meeting.id)
        )
    ).scalar_one_or_none()
    if not speaker:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hablante no encontrado")
    speaker.display_name = data.display_name.strip()
    await audit(db, ctx.org_id, ctx.user.id, "speaker.rename", "speaker", str(speaker.id))
    await db.commit()
    return {"id": str(speaker.id), "label": speaker.label, "display_name": speaker.display_name}


class SpeakerMergeIn(BaseModel):
    into_speaker_id: uuid.UUID


@router.post("/speakers/{speaker_id}/merge")
async def merge_speakers(
    meeting_id: uuid.UUID,
    speaker_id: uuid.UUID,
    data: SpeakerMergeIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Une speaker_id dentro de into_speaker_id (reasigna todos los segmentos)."""
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    if speaker_id == data.into_speaker_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede unir un hablante consigo mismo")
    source = (
        await db.execute(
            select(Speaker).where(Speaker.id == speaker_id, Speaker.meeting_id == meeting.id)
        )
    ).scalar_one_or_none()
    target = (
        await db.execute(
            select(Speaker).where(
                Speaker.id == data.into_speaker_id, Speaker.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if not source or not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hablante no encontrado")

    await db.execute(
        update(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting.id, TranscriptSegment.speaker_id == source.id)
        .values(speaker_id=target.id)
    )
    await db.delete(source)
    await audit(db, ctx.org_id, ctx.user.id, "speaker.merge", "speaker", str(speaker_id))
    await db.commit()
    return {"merged_into": str(target.id)}


class SegmentSpeakerIn(BaseModel):
    speaker_id: uuid.UUID | None


@router.patch("/transcript/{segment_id}/speaker")
async def reassign_segment_speaker(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    data: SegmentSpeakerIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Separar hablantes: reasignar un segmento puntual a otro speaker."""
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    segment = (
        await db.execute(
            select(TranscriptSegment).where(
                TranscriptSegment.id == segment_id, TranscriptSegment.meeting_id == meeting.id
            )
        )
    ).scalar_one_or_none()
    if not segment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento no encontrado")
    if data.speaker_id:
        speaker = (
            await db.execute(
                select(Speaker).where(Speaker.id == data.speaker_id, Speaker.meeting_id == meeting.id)
            )
        ).scalar_one_or_none()
        if not speaker:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Hablante no encontrado")
    segment.speaker_id = data.speaker_id
    await db.commit()
    return {"ok": True}


class SpeakerCreateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


@router.post("/speakers", status_code=201)
async def create_speaker(
    meeting_id: uuid.UUID,
    data: SpeakerCreateIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    count = (
        await db.execute(select(func.count(Speaker.id)).where(Speaker.meeting_id == meeting.id))
    ).scalar()
    speaker = Speaker(
        meeting_id=meeting.id,
        label=f"Speaker {(count or 0) + 1}",
        display_name=data.display_name.strip(),
    )
    db.add(speaker)
    await db.commit()
    await db.refresh(speaker)
    return {"id": str(speaker.id), "label": speaker.label, "display_name": speaker.display_name}
