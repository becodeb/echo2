"""Configuración de IA por organización (LLM, STT, embeddings, diarización).

Las API keys se guardan cifradas y se devuelven SIEMPRE enmascaradas.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import OrgAISettings
from ..security import decrypt_secret, encrypt_secret, mask_secret
from ..services.ai_settings import (
    get_org_ai_settings,
    resolve_embeddings,
    resolve_llm,
    resolve_stt,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/org/ai-settings", tags=["settings"])

LLM_PROVIDERS = ["openai", "anthropic", "gemini", "groq", "openrouter", "orcarouter", "gmi", "ollama"]
STT_PROVIDERS = ["bridge", "openai", "groq", "deepgram"]
EMBEDDING_PROVIDERS = ["openai", "ollama", "none"]


class AISettingsOut(BaseModel):
    llm_provider: str | None
    llm_model: str | None
    llm_api_key_masked: str | None
    llm_base_url: str | None
    llm_temperature: str | None
    stt_provider: str | None
    stt_model: str | None
    stt_api_key_masked: str | None
    embeddings_provider: str | None
    embeddings_model: str | None
    embeddings_api_key_masked: str | None
    diarization_provider: str | None
    minutes_language: str
    available: dict
    # Qué está usando el servidor ahora mismo (provider+modelo, nunca la key).
    # Sin esto "usar default del servidor" es una caja negra.
    effective: dict


class AISettingsIn(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = Field(default=None, max_length=120)
    llm_api_key: str | None = Field(default=None, max_length=500)  # None = sin cambio, "" = borrar
    llm_base_url: str | None = Field(default=None, max_length=300)
    llm_temperature: str | None = None
    stt_provider: str | None = None
    stt_model: str | None = None
    stt_api_key: str | None = Field(default=None, max_length=500)
    embeddings_provider: str | None = None
    embeddings_model: str | None = None
    embeddings_api_key: str | None = Field(default=None, max_length=500)
    diarization_provider: str | None = None
    minutes_language: str | None = None


def _masked(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    plain = decrypt_secret(encrypted)
    return mask_secret(plain) if plain else None


async def _effective(db: AsyncSession, org_id) -> dict:
    """Configuración que realmente se aplica hoy, ya resuelta org → entorno."""
    llm = await resolve_llm(db, org_id)
    stt = await resolve_stt(db, org_id)
    embeddings = await resolve_embeddings(db, org_id)
    return {
        "llm": {"provider": llm.provider, "model": llm.model} if llm else None,
        "stt": {"provider": stt.provider, "model": stt.model or "whisper-1"} if stt else None,
        "embeddings": (
            {"provider": embeddings.provider, "model": embeddings.model} if embeddings else None
        ),
    }


def _serialize(row: OrgAISettings | None, effective: dict) -> AISettingsOut:
    return AISettingsOut(
        llm_provider=row.llm_provider if row else None,
        llm_model=row.llm_model if row else None,
        llm_api_key_masked=_masked(row.llm_api_key_enc) if row else None,
        llm_base_url=row.llm_base_url if row else None,
        llm_temperature=row.llm_temperature if row else None,
        stt_provider=row.stt_provider if row else None,
        stt_model=row.stt_model if row else None,
        stt_api_key_masked=_masked(row.stt_api_key_enc) if row else None,
        embeddings_provider=row.embeddings_provider if row else None,
        embeddings_model=row.embeddings_model if row else None,
        embeddings_api_key_masked=_masked(row.embeddings_api_key_enc) if row else None,
        diarization_provider=row.diarization_provider if row else None,
        minutes_language=row.minutes_language if row else "es",
        available={
            "llm_providers": LLM_PROVIDERS,
            "stt_providers": STT_PROVIDERS,
            "embedding_providers": EMBEDDING_PROVIDERS,
        },
        effective=effective,
    )


@router.get("", response_model=AISettingsOut)
async def get_ai_settings(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    row = await get_org_ai_settings(db, ctx.org_id)
    return _serialize(row, await _effective(db, ctx.org_id))


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

    for field in (
        "llm_provider", "llm_model", "llm_base_url", "llm_temperature",
        "stt_provider", "stt_model",
        "embeddings_provider", "embeddings_model",
        "diarization_provider", "minutes_language",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, value or None)

    # keys: None = no tocar; "" = eliminar; valor = reemplazar (cifrado)
    if data.llm_api_key is not None:
        row.llm_api_key_enc = encrypt_secret(data.llm_api_key) if data.llm_api_key else None
    if data.stt_api_key is not None:
        row.stt_api_key_enc = encrypt_secret(data.stt_api_key) if data.stt_api_key else None
    if data.embeddings_api_key is not None:
        row.embeddings_api_key_enc = (
            encrypt_secret(data.embeddings_api_key) if data.embeddings_api_key else None
        )

    # NUNCA loggear las keys: el audit solo registra qué campos cambiaron
    changed_fields = [
        f for f in ("llm_api_key", "stt_api_key", "embeddings_api_key")
        if getattr(data, f) is not None
    ]
    await audit(
        db, ctx.org_id, ctx.user.id, "ai_settings.update", "settings",
        detail={"changed_keys": changed_fields, "llm_provider": data.llm_provider},
    )
    await db.commit()
    await db.refresh(row)
    return _serialize(row, await _effective(db, ctx.org_id))
