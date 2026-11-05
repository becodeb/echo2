"""Opinión de los usuarios: lo que pregunta Echo y lo que lee Becode en su panel.

Hay dos popups, las estrellitas y "¿qué cambiarías?". Arrancan apagados: se
prenden desde el panel, así un deploy no le salta a todo el colegio.
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user, rate_limit
from ..models import FEEDBACK_KINDS, FeedbackPrompt, FeedbackResponse, Organization, OrganizationMember, User
from ..services.audit import audit
from .admin import get_superadmin

router = APIRouter(tags=["feedback"])

DEFAULT_PROMPTS = {
    "stars": {
        "title": "Queremos saber tu opinión",
        "question": "¿Cómo viene siendo Echo para vos?",
    },
    "suggestion": {
        "title": "Una pregunta rápida",
        "question": "¿Qué cambiarías para mejorar tu día a día con Echo?",
    },
}
DEFAULT_EVERY_DAYS = 60
# Que primero la use un poco, y que nunca le salten dos popups seguidos.
NEW_ACCOUNT_DAYS = 3
MIN_GAP_DAYS = 7
MAX_TEXT_CHARS = 2000
RESPONSES_PER_HOUR = 20

Kind = Literal["stars", "suggestion"]


class PromptOut(BaseModel):
    kind: str
    enabled: bool
    title: str
    question: str
    every_days: int


async def _prompts(db: AsyncSession) -> list[PromptOut]:
    rows = {row.kind: row for row in (await db.execute(select(FeedbackPrompt))).scalars()}
    out = []
    for kind in FEEDBACK_KINDS:
        row = rows.get(kind)
        out.append(
            PromptOut(
                kind=kind,
                enabled=row.enabled if row else False,
                title=row.title if row else DEFAULT_PROMPTS[kind]["title"],
                question=row.question if row else DEFAULT_PROMPTS[kind]["question"],
                every_days=row.every_days if row else DEFAULT_EVERY_DAYS,
            )
        )
    return out


@router.get("/api/feedback/prompt", response_model=PromptOut | None)
async def next_prompt(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Lo que hay que preguntarle ahora a esta persona, o nada."""
    prompts = [prompt for prompt in await _prompts(db) if prompt.enabled]
    now = datetime.now(UTC)
    if not prompts or user.created_at > now - timedelta(days=NEW_ACCOUNT_DAYS):
        return None
    last = dict(
        (
            await db.execute(
                select(FeedbackResponse.kind, func.max(FeedbackResponse.created_at))
                .where(FeedbackResponse.user_id == user.id)
                .group_by(FeedbackResponse.kind)
            )
        ).all()
    )
    if any(at > now - timedelta(days=MIN_GAP_DAYS) for at in last.values()):
        return None
    for prompt in prompts:
        at = last.get(prompt.kind)
        if at is None or at <= now - timedelta(days=prompt.every_days):
            return prompt
    return None


async def _current_org(
    db: AsyncSession, user: User, x_organization_id: str | None
) -> uuid.UUID | None:
    """La sede activa, solo si de verdad es de esta persona."""
    try:
        org_id = uuid.UUID(x_organization_id or "")
    except ValueError:
        return None
    found = (
        await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id
            )
        )
    ).first()
    return org_id if found else None


class AnswerIn(BaseModel):
    kind: Kind
    stars: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


@router.post("/api/feedback", status_code=201)
async def answer(
    data: AnswerIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_organization_id: str | None = Header(default=None),
):
    rate_limit(f"feedback:{user.id}", RESPONSES_PER_HOUR, 3600)
    text = (data.text or "").strip() or None
    if data.kind == "stars" and data.stars is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elegí de 1 a 5 estrellas")
    if data.kind == "suggestion" and not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contanos qué cambiarías")
    db.add(
        FeedbackResponse(
            user_id=user.id,
            organization_id=await _current_org(db, user, x_organization_id),
            kind=data.kind,
            stars=data.stars if data.kind == "stars" else None,
            text=text,
        )
    )
    await db.commit()
    return {"ok": True}


class DismissIn(BaseModel):
    kind: Kind


@router.post("/api/feedback/dismiss", status_code=204)
async def dismiss(
    data: DismissIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """"Ahora no": cuenta igual que responder para no volver a preguntar enseguida."""
    db.add(FeedbackResponse(user_id=user.id, kind=data.kind, dismissed=True))
    await db.commit()


# ── Panel de Becode ──────────────────────────────────────────────


class ResponseOut(BaseModel):
    id: uuid.UUID
    kind: str
    stars: int | None
    text: str | None
    created_at: datetime
    user_name: str
    user_email: str
    organization: str | None


class FeedbackOverview(BaseModel):
    prompts: list[PromptOut]
    # Cuántas respuestas hay de cada puntaje, de 1 a 5.
    distribution: list[int]
    average: float | None
    suggestions: int
    dismissed: int
    responses: list[ResponseOut]


@router.get("/api/admin/feedback", response_model=FeedbackOverview)
async def overview(_: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)):
    counts = dict(
        (
            await db.execute(
                select(FeedbackResponse.stars, func.count())
                .where(FeedbackResponse.stars.is_not(None))
                .group_by(FeedbackResponse.stars)
            )
        ).all()
    )
    distribution = [counts.get(stars, 0) for stars in range(1, 6)]
    total = sum(distribution)
    suggestions = (
        await db.execute(
            select(func.count()).select_from(FeedbackResponse).where(
                FeedbackResponse.kind == "suggestion", FeedbackResponse.dismissed.is_(False)
            )
        )
    ).scalar_one()
    dismissed = (
        await db.execute(select(func.count()).select_from(FeedbackResponse).where(FeedbackResponse.dismissed.is_(True)))
    ).scalar_one()
    rows = (
        await db.execute(
            select(FeedbackResponse, User.name, User.email, Organization.name)
            .join(User, User.id == FeedbackResponse.user_id)
            .outerjoin(Organization, Organization.id == FeedbackResponse.organization_id)
            .where(FeedbackResponse.dismissed.is_(False))
            .order_by(FeedbackResponse.created_at.desc())
            .limit(300)
        )
    ).all()
    return FeedbackOverview(
        prompts=await _prompts(db),
        distribution=distribution,
        average=round(sum((i + 1) * n for i, n in enumerate(distribution)) / total, 1) if total else None,
        suggestions=suggestions,
        dismissed=dismissed,
        responses=[
            ResponseOut(
                id=row.id, kind=row.kind, stars=row.stars, text=row.text, created_at=row.created_at,
                user_name=name, user_email=email, organization=org,
            )
            for row, name, email, org in rows
        ],
    )


class PromptIn(BaseModel):
    enabled: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    question: str | None = Field(default=None, min_length=1, max_length=300)
    every_days: int | None = Field(default=None, ge=7, le=365)


@router.put("/api/admin/feedback/prompts/{kind}", response_model=PromptOut)
async def set_prompt(
    kind: Kind, data: PromptIn, admin: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)
):
    row = await db.get(FeedbackPrompt, kind)
    if row is None:
        row = FeedbackPrompt(kind=kind, every_days=DEFAULT_EVERY_DAYS, **DEFAULT_PROMPTS[kind])
        db.add(row)
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.title is not None:
        row.title = data.title.strip()
    if data.question is not None:
        row.question = data.question.strip()
    if data.every_days is not None:
        row.every_days = data.every_days
    await audit(
        db, None, admin.id, "admin.feedback_prompt", "feedback_prompt", kind,
        detail={"by": admin.email, "enabled": row.enabled},
    )
    await db.commit()
    return PromptOut(
        kind=kind, enabled=row.enabled, title=row.title, question=row.question, every_days=row.every_days
    )
