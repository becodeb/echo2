"""Resolución de configuración efectiva de IA por organización.

Prioridad: settings de la organización (keys cifradas en DB) → defaults
globales del entorno (.env). Nunca se expone la key completa al frontend.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import OrgAISettings, OrgDictionaryEntry
from ..security import decrypt_secret


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    temperature: float = 0.2


@dataclass
class SttConfig:
    provider: str  # bridge|openai|groq|deepgram|fake
    model: str | None
    api_key: str


@dataclass
class EmbeddingsConfig:
    provider: str  # openai|ollama|none
    model: str
    api_key: str
    base_url: str | None = None


async def get_org_ai_settings(db: AsyncSession, org_id: uuid.UUID) -> OrgAISettings | None:
    return (
        await db.execute(select(OrgAISettings).where(OrgAISettings.organization_id == org_id))
    ).scalar_one_or_none()


async def resolve_llm(db: AsyncSession, org_id: uuid.UUID) -> LLMConfig | None:
    env = get_settings()
    row = await get_org_ai_settings(db, org_id)
    if row and row.llm_provider:
        key = decrypt_secret(row.llm_api_key_enc) if row.llm_api_key_enc else ""
        if not key:
            key = _env_key_for(row.llm_provider)
        if key or row.llm_provider == "ollama":
            temperature = 0.2
            try:
                if row.llm_temperature:
                    temperature = float(row.llm_temperature)
            except ValueError:
                pass
            return LLMConfig(
                provider=row.llm_provider,
                model=row.llm_model or _default_model(row.llm_provider),
                api_key=key,
                base_url=row.llm_base_url or (env.ollama_base_url if row.llm_provider == "ollama" else None),
                temperature=temperature,
            )
    # defaults de entorno
    if env.anthropic_api_key:
        return LLMConfig("anthropic", "claude-sonnet-5", env.anthropic_api_key)
    if env.openai_api_key:
        return LLMConfig("openai", "gpt-4o-mini", env.openai_api_key)
    if env.groq_api_key:
        return LLMConfig("groq", "llama-3.3-70b-versatile", env.groq_api_key)
    if env.openrouter_api_key:
        return LLMConfig("openrouter", "anthropic/claude-sonnet-4.5", env.openrouter_api_key)
    if env.ollama_base_url:
        return LLMConfig("ollama", "llama3.1", "", base_url=env.ollama_base_url)
    return None


async def resolve_stt(db: AsyncSession, org_id: uuid.UUID) -> SttConfig | None:
    env = get_settings()
    row = await get_org_ai_settings(db, org_id)
    if row and row.stt_provider and row.stt_provider != "bridge":
        key = decrypt_secret(row.stt_api_key_enc) if row.stt_api_key_enc else ""
        if not key:
            key = _env_key_for(row.stt_provider)
        if key:
            return SttConfig(provider=row.stt_provider, model=row.stt_model, api_key=key)
    if env.openai_api_key:
        return SttConfig(provider="openai", model=None, api_key=env.openai_api_key)
    if env.groq_api_key:
        return SttConfig(provider="groq", model=None, api_key=env.groq_api_key)
    if env.deepgram_api_key:
        return SttConfig(provider="deepgram", model=None, api_key=env.deepgram_api_key)
    return None


async def resolve_embeddings(db: AsyncSession, org_id: uuid.UUID) -> EmbeddingsConfig | None:
    env = get_settings()
    row = await get_org_ai_settings(db, org_id)
    if row and row.embeddings_provider:
        if row.embeddings_provider == "none":
            return None
        key = decrypt_secret(row.embeddings_api_key_enc) if row.embeddings_api_key_enc else ""
        if not key:
            key = _env_key_for(row.embeddings_provider)
        if key or row.embeddings_provider == "ollama":
            return EmbeddingsConfig(
                provider=row.embeddings_provider,
                model=row.embeddings_model
                or ("text-embedding-3-small" if row.embeddings_provider == "openai" else "nomic-embed-text"),
                api_key=key,
                base_url=env.ollama_base_url if row.embeddings_provider == "ollama" else None,
            )
    if env.openai_api_key:
        return EmbeddingsConfig("openai", "text-embedding-3-small", env.openai_api_key)
    if env.ollama_base_url:
        return EmbeddingsConfig("ollama", "nomic-embed-text", "", base_url=env.ollama_base_url)
    return None


async def get_vocabulary(db: AsyncSession, org_id: uuid.UUID) -> list[str]:
    rows = (
        (
            await db.execute(
                select(OrgDictionaryEntry.term).where(OrgDictionaryEntry.organization_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _env_key_for(provider: str) -> str:
    env = get_settings()
    return {
        "openai": env.openai_api_key,
        "anthropic": env.anthropic_api_key,
        "groq": env.groq_api_key,
        "deepgram": env.deepgram_api_key,
        "openrouter": env.openrouter_api_key,
    }.get(provider, "")


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-5",
        "gemini": "gemini-2.0-flash",
        "groq": "llama-3.3-70b-versatile",
        "openrouter": "anthropic/claude-sonnet-4.5",
        "ollama": "llama3.1",
    }.get(provider, "gpt-4o-mini")
