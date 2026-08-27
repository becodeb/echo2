"""Acta: lectura, edición (nueva versión), estados, plantillas y resúmenes."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import (
    MeetingSummary,
    Minutes,
    MinutesTemplate,
    MinutesVersion,
    Notification,
    OrganizationMember,
)
from ..services.ai_settings import resolve_llm
from ..services.audit import audit
from ..services.llm import get_llm_provider
from ..services.minutes_gen import DEFAULT_TEMPLATE, generate_minutes, get_active_template

router = APIRouter(tags=["minutes"])


class MinutesVersionOut(BaseModel):
    version: int
    body_markdown: str
    verification: list | None
    note: str | None
    model_used: str | None
    created_at: datetime
    created_by: uuid.UUID | None


class MinutesOut(BaseModel):
    id: uuid.UUID
    status: str
    current_version: int
    approved_at: datetime | None
    version: MinutesVersionOut | None
    versions: list[dict]


@router.get("/api/meetings/{meeting_id}/minutes", response_model=MinutesOut | None)
async def get_minutes(
    meeting_id: uuid.UUID,
    version: int | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    minutes = (
        await db.execute(select(Minutes).where(Minutes.meeting_id == meeting.id))
    ).scalar_one_or_none()
    if not minutes:
        return None
    target_version = version or minutes.current_version
    row = (
        await db.execute(
            select(MinutesVersion).where(
                MinutesVersion.minutes_id == minutes.id, MinutesVersion.version == target_version
            )
        )
    ).scalar_one_or_none()
    all_versions = (
        (
            await db.execute(
                select(MinutesVersion)
                .where(MinutesVersion.minutes_id == minutes.id)
                .order_by(MinutesVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return MinutesOut(
        id=minutes.id,
        status=minutes.status,
        current_version=minutes.current_version,
        approved_at=minutes.approved_at,
        version=MinutesVersionOut(
            version=row.version,
            body_markdown=row.body_markdown,
            verification=row.verification,
            note=row.note,
            model_used=row.model_used,
            created_at=row.created_at,
            created_by=row.created_by,
        )
        if row
        else None,
        versions=[
            {
                "version": v.version,
                "note": v.note,
                "created_at": v.created_at.isoformat(),
                "model_used": v.model_used,
            }
            for v in all_versions
        ],
    )


@router.post("/api/meetings/{meeting_id}/minutes/generate", status_code=202)
async def regenerate_minutes(
    meeting_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    llm_config = await resolve_llm(db, ctx.org_id)
    if llm_config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No hay modelo de IA configurado (Ajustes → IA)"
        )
    provider = get_llm_provider(
        llm_config.provider, llm_config.api_key, llm_config.model, llm_config.base_url
    )
    background.add_task(generate_minutes, meeting.id, provider)
    await audit(db, ctx.org_id, ctx.user.id, "minutes.regenerate", "meeting", str(meeting.id))
    await db.commit()
    return {"status": "generating"}


class MinutesEditIn(BaseModel):
    body_markdown: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=300)


@router.post("/api/meetings/{meeting_id}/minutes/versions", response_model=MinutesOut)
async def save_minutes_edit(
    meeting_id: uuid.UUID,
    data: MinutesEditIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")
    minutes = (
        await db.execute(select(Minutes).where(Minutes.meeting_id == meeting.id))
    ).scalar_one_or_none()
    if not minutes:
        minutes = Minutes(
            meeting_id=meeting.id, organization_id=ctx.org_id, status="draft", current_version=0
        )
        db.add(minutes)
        await db.flush()
    next_version = minutes.current_version + 1
    db.add(
        MinutesVersion(
            minutes_id=minutes.id,
            version=next_version,
            body_markdown=data.body_markdown,
            note=data.note or f"Editada por {ctx.user.name}",
            created_by=ctx.user.id,
        )
    )
    minutes.current_version = next_version
    if minutes.status == "approved":
        minutes.status = "in_review"  # una edición sobre acta aprobada la vuelve a revisión
    await audit(db, ctx.org_id, ctx.user.id, "minutes.edit", "minutes", str(minutes.id))
    await db.commit()
    return await get_minutes(meeting_id, None, ctx, db)


class MinutesStatusIn(BaseModel):
    status: str = Field(pattern="^(draft|in_review|approved)$")


@router.patch("/api/meetings/{meeting_id}/minutes/status", response_model=MinutesOut)
async def change_minutes_status(
    meeting_id: uuid.UUID,
    data: MinutesStatusIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    minutes = (
        await db.execute(select(Minutes).where(Minutes.meeting_id == meeting.id))
    ).scalar_one_or_none()
    if not minutes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay acta para esta reunión")
    if data.status == "approved":
        ctx.require_role("admin")
        minutes.approved_by = ctx.user.id
        minutes.approved_at = datetime.now(UTC)
        # notificar aprobación
        members = (
            (
                await db.execute(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == ctx.org_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in members:
            db.add(
                Notification(
                    user_id=user_id,
                    organization_id=ctx.org_id,
                    kind="minutes_approved",
                    title=f"El acta de «{meeting.title}» fue aprobada",
                    link=f"/meetings/{meeting.id}",
                )
            )
    minutes.status = data.status
    await audit(db, ctx.org_id, ctx.user.id, f"minutes.status.{data.status}", "minutes", str(minutes.id))
    await db.commit()
    return await get_minutes(meeting_id, None, ctx, db)


# ── Resúmenes ────────────────────────────────────────────────────


@router.get("/api/meetings/{meeting_id}/summary")
async def get_summaries(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    rows = (
        (
            await db.execute(
                select(MeetingSummary).where(MeetingSummary.meeting_id == meeting.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        row.kind: {"content": row.content, "model_used": row.model_used, "created_at": row.created_at.isoformat()}
        for row in rows
    }


# ── Plantillas de acta ───────────────────────────────────────────


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    body_markdown: str = Field(min_length=1)


@router.get("/api/org/minutes-template")
async def get_template(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    template = await get_active_template(db, ctx.org_id)
    return {
        "id": str(template.id),
        "name": template.name,
        "body_markdown": template.body_markdown,
        "is_provisional": template.is_provisional,
    }


@router.put("/api/org/minutes-template")
async def update_template(
    data: TemplateIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    """Carga el MODELO REAL de acta de la organización (pasa a ser source of truth)."""
    ctx.require_role("admin")
    template = await get_active_template(db, ctx.org_id)
    template.name = data.name
    template.body_markdown = data.body_markdown
    template.is_provisional = False
    await audit(db, ctx.org_id, ctx.user.id, "minutes_template.update", "template", str(template.id))
    await db.commit()
    return {
        "id": str(template.id),
        "name": template.name,
        "body_markdown": template.body_markdown,
        "is_provisional": template.is_provisional,
    }


@router.post("/api/org/minutes-template/reset")
async def reset_template(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("admin")
    template = await get_active_template(db, ctx.org_id)
    template.name = "Acta estándar (provisional)"
    template.body_markdown = DEFAULT_TEMPLATE
    template.is_provisional = True
    await db.commit()
    return {"ok": True}
