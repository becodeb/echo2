"""Ajustes de IA de una organización: solo el idioma del acta.

Los colegios no eligen modelo ni cargan keys: las pone Becode (la
transcripción es siempre Groq; el modelo de IA lo define el superadmin en
/admin, para todas o para una sede). Lo que una sede haya guardado antes en
esas columnas no se usa (services/ai_settings.py).
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import OrgAISettings
from ..services.ai_settings import get_org_ai_settings
from ..services.audit import audit

router = APIRouter(prefix="/api/org/ai-settings", tags=["settings"])


class AISettingsOut(BaseModel):
    minutes_language: str


class AISettingsIn(BaseModel):
    minutes_language: Literal["es", "en", "pt"]


@router.get("", response_model=AISettingsOut)
async def get_ai_settings(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    row = await get_org_ai_settings(db, ctx.org_id)
    return AISettingsOut(minutes_language=(row.minutes_language if row else None) or "es")


@router.put("", response_model=AISettingsOut)
async def update_ai_settings(
    data: AISettingsIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    row = await get_org_ai_settings(db, ctx.org_id)
    if not row:
        row = OrgAISettings(organization_id=ctx.org_id)
        db.add(row)
    row.minutes_language = data.minutes_language
    await audit(
        db, ctx.org_id, ctx.user.id, "ai_settings.update", "settings",
        detail={"minutes_language": data.minutes_language},
    )
    await db.commit()
    return AISettingsOut(minutes_language=row.minutes_language)
