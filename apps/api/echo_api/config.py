"""Configuración central del API de Echo (pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    echo_env: str = "development"

    database_url: str = "postgresql+asyncpg://echo:echo_dev_pw@localhost:5433/echo"

    jwt_secret: str = "dev_only_insecure_secret_change_me"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    # Clave Fernet para cifrar API keys de providers en reposo.
    # Si está vacía en desarrollo se deriva una del jwt_secret (con warning).
    encryption_key: str = ""

    web_origin: str = "http://localhost:5173"
    api_public_url: str = "http://localhost:8000"

    # Defaults globales de providers (cada organización puede configurar el suyo)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    deepgram_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = ""

    # Límites
    max_upload_mb: int = 500
    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 30

    @property
    def is_production(self) -> bool:
        return self.echo_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
