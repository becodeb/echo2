"""CRUD de reuniones + ciclo de vida (start / pause / resume / finish)."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import (
    ActionItem,
    Bookmark,
    Decision,
    Meeting,
    MeetingParticipant,
    Project,
    ProjectMeeting,
    Question,
    Speaker,
    TranscriptSegment,
)
from ..services.audit import audit
from ..services.pipeline import run_finalize_pipeline
from ..services.live_bus import live_bus

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    role_label: str | None = None


class MeetingCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    language: str = Field(default="es", max_length=10)
    audio_source: str = Field(default="browser")
    stt_engine: str | None = None
    project_id: uuid.UUID | None = None
    participants: list[ParticipantIn] = []
    visibility: str = Field(default="org")  # org|private


class ParticipantOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    role_label: str | None

    class Config:
        from_attributes = True


class SpeakerOut(BaseModel):
    id: uuid.UUID
    label: str
    display_name: str | None
    color: str
    identity_suggestion: dict | None

    class Config:
        from_attributes = True


class MeetingOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    language: str
    audio_source: str
    stt_engine: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    created_at: datetime
    created_by: uuid.UUID
    processing_state: dict
    meta: dict
    participants: list[ParticipantOut] = []
    speakers: list[SpeakerOut] = []


class MeetingListItem(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    started_at: datetime | None
    duration_seconds: int
    created_at: datetime
    participant_count: int
    project_name: str | None = None


def _meeting_out(m: Meeting, participants: list, speakers: list) -> MeetingOut:
    return MeetingOut(
        id=m.id,
        title=m.title,
        status=m.status,
        language=m.language,
        audio_source=m.audio_source,
        stt_engine=m.stt_engine,
        started_at=m.started_at,
        ended_at=m.ended_at,
        duration_seconds=m.duration_seconds,
        created_at=m.created_at,
        created_by=m.created_by,
        processing_state=m.processing_state or {},
        meta=m.meta or {},
        participants=[ParticipantOut.model_validate(p) for p in participants],
        speakers=[SpeakerOut.model_validate(s) for s in speakers],
    )


@router.post("", response_model=MeetingOut, status_code=201)
async def create_meeting(
    data: MeetingCreateIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    meeting = Meeting(
        organization_id=ctx.org_id,
        created_by=ctx.user.id,
        title=data.title.strip(),
        language=data.language,
        audio_source=data.audio_source,
        stt_engine=data.stt_engine,
        status="draft",
        meta={"visibility": data.visibility if data.visibility in ("org", "private") else "org"},
    )
    db.add(meeting)
    await db.flush()

    participants = []
    for p in data.participants:
        mp = MeetingParticipant(
            meeting_id=meeting.id, name=p.name.strip(), email=p.email, role_label=p.role_label
        )
        db.add(mp)
        participants.append(mp)

    if data.project_id:
        project = (
            await db.execute(
                select(Project).where(
                    Project.id == data.project_id, Project.organization_id == ctx.org_id
                )
            )
        ).scalar_one_or_none()
        if not project:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")
        db.add(ProjectMeeting(project_id=project.id, meeting_id=meeting.id))

    await audit(db, ctx.org_id, ctx.user.id, "meeting.create", "meeting", str(meeting.id))
    await db.commit()
    await db.refresh(meeting)
    return _meeting_out(meeting, participants, [])


@router.get("", response_model=list[MeetingListItem])
async def list_meetings(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    project_id: uuid.UUID | None = None,
):
    q = (
        select(
            Meeting,
            func.count(MeetingParticipant.id).label("pcount"),
        )
        .outerjoin(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        .where(Meeting.organization_id == ctx.org_id, Meeting.deleted_at.is_(None))
        .group_by(Meeting.id)
        .order_by(Meeting.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        q = q.where(Meeting.status == status_filter)
    if project_id:
        q = q.join(ProjectMeeting, ProjectMeeting.meeting_id == Meeting.id).where(
            ProjectMeeting.project_id == project_id
        )
    rows = (await db.execute(q)).all()

    # nombre de proyecto (si tiene)
    meeting_ids = [m.id for m, _ in rows]
    project_names: dict[uuid.UUID, str] = {}
    if meeting_ids:
        prows = (
            await db.execute(
                select(ProjectMeeting.meeting_id, Project.name)
                .join(Project, Project.id == ProjectMeeting.project_id)
                .where(ProjectMeeting.meeting_id.in_(meeting_ids))
            )
        ).all()
        project_names = {mid: name for mid, name in prows}

    out = []
    for m, pcount in rows:
        visibility = (m.meta or {}).get("visibility", "org")
        if visibility == "private" and m.created_by != ctx.user.id and ctx.role not in ("admin", "owner"):
            continue
        out.append(
            MeetingListItem(
                id=m.id,
                title=m.title,
                status=m.status,
                started_at=m.started_at,
                duration_seconds=m.duration_seconds,
                created_at=m.created_at,
                participant_count=pcount,
                project_name=project_names.get(m.id),
            )
        )
    return out


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    participants = (
        (
            await db.execute(
                select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id)
            )
        )
        .scalars()
        .all()
    )
    speakers = (
        (await db.execute(select(Speaker).where(Speaker.meeting_id == meeting.id).order_by(Speaker.label)))
        .scalars()
        .all()
    )
    return _meeting_out(meeting, participants, speakers)


class MeetingUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    language: str | None = None
    visibility: str | None = None


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    data: MeetingUpdateIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    if data.title:
        meeting.title = data.title.strip()
    if data.language:
        meeting.language = data.language
    if data.visibility in ("org", "private"):
        meeting.meta = {**(meeting.meta or {}), "visibility": data.visibility}
    await db.commit()
    return await get_meeting(meeting_id, ctx, db)


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if meeting.created_by != ctx.user.id:
        ctx.require_role("admin")
    meeting.deleted_at = datetime.now(UTC)
    await audit(db, ctx.org_id, ctx.user.id, "meeting.delete", "meeting", str(meeting.id))
    await db.commit()


# ── Ciclo de vida ────────────────────────────────────────────────


@router.post("/{meeting_id}/start", response_model=MeetingOut)
async def start_meeting(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    # "live" es idempotente: si el navegador se cerró o se recargó la página, la
    # reunión sigue live en el servidor y reconectar no debe fallar.
    if meeting.status not in ("draft", "paused", "live"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"No se puede iniciar desde estado {meeting.status}")
    if meeting.status == "draft":
        meeting.started_at = datetime.now(UTC)
    meeting.status = "live"
    await audit(db, ctx.org_id, ctx.user.id, "meeting.start", "meeting", str(meeting.id))
    await db.commit()
    await live_bus.publish(str(meeting.id), {"type": "status", "status": "live"})
    return await get_meeting(meeting_id, ctx, db)


@router.post("/{meeting_id}/pause", response_model=MeetingOut)
async def pause_meeting(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if meeting.status != "live":
        raise HTTPException(status.HTTP_409_CONFLICT, "La reunión no está en vivo")
    meeting.status = "paused"
    await db.commit()
    await live_bus.publish(str(meeting.id), {"type": "status", "status": "paused"})
    return await get_meeting(meeting_id, ctx, db)


@router.post("/{meeting_id}/finish", response_model=MeetingOut)
async def finish_meeting(
    meeting_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    if meeting.status not in ("live", "paused"):
        raise HTTPException(status.HTTP_409_CONFLICT, "La reunión no está activa")

    meeting.status = "processing"
    meeting.ended_at = datetime.now(UTC)
    if meeting.started_at:
        meeting.duration_seconds = int((meeting.ended_at - meeting.started_at).total_seconds())
    # el último timestamp del transcript es más preciso que el reloj
    last_ms = (
        await db.execute(
            select(func.max(TranscriptSegment.end_ms)).where(
                TranscriptSegment.meeting_id == meeting.id
            )
        )
    ).scalar()
    if last_ms:
        meeting.duration_seconds = max(meeting.duration_seconds, int(last_ms / 1000))
    meeting.processing_state = {"stage": "queued", "progress": 0}
    await audit(db, ctx.org_id, ctx.user.id, "meeting.finish", "meeting", str(meeting.id))
    await db.commit()

    await live_bus.publish(str(meeting.id), {"type": "status", "status": "processing"})
    background.add_task(run_finalize_pipeline, str(meeting.id))
    return await get_meeting(meeting_id, ctx, db)


# ── Marcadores durante la reunión ────────────────────────────────


class BookmarkIn(BaseModel):
    kind: str = Field(pattern="^(important|note|decision|task|moment)$")
    at_ms: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=2000)


class BookmarkOut(BookmarkIn):
    id: uuid.UUID
    created_by: uuid.UUID

    class Config:
        from_attributes = True


@router.post("/{meeting_id}/bookmarks", response_model=BookmarkOut, status_code=201)
async def add_bookmark(
    meeting_id: uuid.UUID,
    data: BookmarkIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    bookmark = Bookmark(
        meeting_id=meeting.id, created_by=ctx.user.id, kind=data.kind, at_ms=data.at_ms, note=data.note
    )
    db.add(bookmark)
    await db.commit()
    await db.refresh(bookmark)
    return bookmark


@router.get("/{meeting_id}/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    rows = (
        (
            await db.execute(
                select(Bookmark).where(Bookmark.meeting_id == meeting.id).order_by(Bookmark.at_ms)
            )
        )
        .scalars()
        .all()
    )
    return rows


# ── Insights de una reunión (lectura) ────────────────────────────


class InsightsOut(BaseModel):
    decisions: list[dict]
    action_items: list[dict]
    questions: list[dict]


@router.get("/{meeting_id}/insights", response_model=InsightsOut)
async def get_insights(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)

    def _ser(rows, fields):
        return [
            {f: (str(getattr(r, f)) if f == "id" else getattr(r, f)) for f in fields} for r in rows
        ]

    decisions = (
        (await db.execute(select(Decision).where(Decision.meeting_id == meeting.id).order_by(Decision.created_at)))
        .scalars()
        .all()
    )
    actions = (
        (await db.execute(select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.created_at)))
        .scalars()
        .all()
    )
    questions = (
        (await db.execute(select(Question).where(Question.meeting_id == meeting.id).order_by(Question.created_at)))
        .scalars()
        .all()
    )
    return InsightsOut(
        decisions=_ser(decisions, ["id", "text", "context", "evidence_start_ms", "evidence_end_ms", "status", "source"]),
        action_items=[
            {
                "id": str(a.id),
                "text": a.text,
                "assignee_name": a.assignee_name,
                "due_text": a.due_text,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "status": a.status,
                "evidence_start_ms": a.evidence_start_ms,
                "evidence_end_ms": a.evidence_end_ms,
                "source": a.source,
            }
            for a in actions
        ],
        questions=_ser(questions, ["id", "text", "resolved", "evidence_start_ms", "evidence_end_ms"]),
    )
