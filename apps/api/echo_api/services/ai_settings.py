"""Resolución de configuración efectiva de IA por organización.

`resolve_llm` baja por CUATRO niveles y devuelve el primero que resuelve:

  1. **Organización** (`OrgAISettings`, key cifrada en DB) — solo la carga el
     superadmin desde `/admin` (los colegios no eligen modelo ni ponen keys:
     las pone Becode).
  2. **Servidor** (`ServerAISettings`, fila única en DB) — el default de la
     instalación que carga el superadmin en `/admin`. Va ANTES que el entorno
     a propósito: es lo que permite cambiar la key sin redeploy.
  3. **Entorno explícito** — `DEFAULT_LLM_PROVIDER` + `DEFAULT_LLM_MODEL`.
  4. **Autodetección** — la primera key presente en el entorno, en orden fijo:
     anthropic → openai → groq → openrouter → orcarouter → gmi → ollama.

Si ninguno resuelve devuelve `None`: no hay IA configurada, y quien llama
saltea la etapa en vez de simularla.

Dos matices que sorprenden:

- Elegir provider sin cargar key NO salta al nivel siguiente por sí solo: se
  busca la key de ESE provider en el entorno (`_env_key_for`). Recién si no
  hay ninguna se baja de nivel. O sea, el provider de la org se respeta
  aunque la key venga del `.env`. `ollama` es la excepción: no necesita key.
- `resolve_llm` con un `org_id` inexistente saltea el nivel 1 y devuelve el
  default puro de la instalación. Es un truco deliberado, no un accidente:
  lo usa el panel de admin para probar la conexión sin tomar prestada la
  configuración de ninguna organización.

`resolve_stt` y `resolve_embeddings` solo miran el entorno: la transcripción
es siempre Groq con la key de Becode (OpenAI no recibe audio, ni como
respaldo; docs/plan-correcciones.md §1.2) y los embeddings los pone el
servidor. Lo que un colegio haya guardado antes en esas columnas no se usa.

Nunca se expone la key completa al frontend.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import OrgAISettings, ServerAISettings, OrgDictionaryEntry
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
    provider: str  # groq (o fake en los tests)
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
    # Default de la instalación cargado por el superadmin. Va antes que las
    # variables de entorno: es lo que permite cambiar la key sin redeploy.
    server = (
        await db.execute(select(ServerAISettings).limit(1))
    ).scalar_one_or_none()
    if server and server.llm_provider:
        key = decrypt_secret(server.llm_api_key_enc) if server.llm_api_key_enc else ""
        if not key:
            key = _env_key_for(server.llm_provider)
        if key or server.llm_provider == "ollama":
            return LLMConfig(
                provider=server.llm_provider,
                model=server.llm_model or _default_model(server.llm_provider),
                api_key=key,
                base_url=server.llm_base_url
                or (env.ollama_base_url if server.llm_provider == "ollama" else None),
            )

    # defaults de entorno
    if env.default_llm_provider:
        provider = env.default_llm_provider
        key = _env_key_for(provider)
        if key or provider == "ollama":
            return LLMConfig(
                provider,
                _env_default_model(provider),
                key,
                base_url=env.ollama_base_url if provider == "ollama" else None,
            )
    if env.anthropic_api_key:
        return LLMConfig("anthropic", _env_default_model("anthropic"), env.anthropic_api_key)
    if env.openai_api_key:
        return LLMConfig("openai", _env_default_model("openai"), env.openai_api_key)
    if env.groq_api_key:
        return LLMConfig("groq", _env_default_model("groq"), env.groq_api_key)
    if env.openrouter_api_key:
        return LLMConfig("openrouter", _env_default_model("openrouter"), env.openrouter_api_key)
    if env.orcarouter_api_key:
        return LLMConfig("orcarouter", _env_default_model("orcarouter"), env.orcarouter_api_key)
    if env.gmi_api_key:
        return LLMConfig("gmi", _env_default_model("gmi"), env.gmi_api_key)
    if env.ollama_base_url:
        return LLMConfig("ollama", "llama3.1", "", base_url=env.ollama_base_url)
    return None


async def resolve_stt(db: AsyncSession, org_id: uuid.UUID) -> SttConfig | None:
    """Groq whisper-large-v3-turbo con la key de Becode, para todas las sedes.

    Sin respaldo en otro proveedor: si Groq se cae, se reintenta y el audio de
    trabajo queda guardado para transcribirlo después (services/diarization.py).
    """
    env = get_settings()
    if env.groq_api_key:
        return SttConfig(provider="groq", model=None, api_key=env.groq_api_key)
    return None


async def resolve_embeddings(db: AsyncSession, org_id: uuid.UUID) -> EmbeddingsConfig | None:
    env = get_settings()
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
        "elevenlabs": env.elevenlabs_api_key,
        "deepgram": env.deepgram_api_key,
        "openrouter": env.openrouter_api_key,
        "gmi": env.gmi_api_key,
        "orcarouter": env.orcarouter_api_key,
        "vercel": env.ai_gateway_api_key,
        "deepseek": env.deepseek_api_key,
    }.get(provider, "")


def _env_default_model(provider: str) -> str:
    """Modelo del default del servidor: lo configurado gana sobre el built-in."""
    return get_settings().default_llm_model or _default_model(provider)


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-6-luna",
        "anthropic": "claude-sonnet-5",
        "gemini": "gemini-2.0-flash",
        # Groq retiró llama-3.3-70b (404 el 30/9/2026); gpt-oss-120b anda bien en castellano.
        "groq": "openai/gpt-oss-120b",
        "openrouter": "anthropic/claude-sonnet-4.5",
        "gmi": "MiniMaxAI/MiniMax-M3",
        "orcarouter": "orcarouter/free",
        "vercel": "deepseek/deepseek-v4-pro",
        "deepseek": "deepseek-v4-pro",
        "ollama": "llama3.1",
    }.get(provider, "gpt-4o-mini")
