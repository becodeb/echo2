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

    # Google OAuth (crear cuenta / iniciar sesión con Google). Si el id o el
    # secret están vacíos, la app no ofrece el botón y el endpoint no existe
    # a efectos prácticos: el flujo entero queda apagado.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Por defecto se deriva de api_public_url; se puede fijar a mano si el
    # callback registrado en Google apunta a otro host.
    google_redirect_uri: str = ""

    # Superadmins de la instalación, separados por coma. Se sincronizan al
    # arrancar. Deliberadamente fuera de la app: nadie se asciende a sí mismo
    # desde la UI, se cambia acá y se reinicia.
    superadmin_emails: str = ""

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_callback_url(self) -> str:
        if self.google_redirect_uri:
            return self.google_redirect_uri
        return self.api_public_url.rstrip("/") + "/api/auth/google/callback"

    # Proveedor LLM por defecto cuando la organización no configuró ninguno.
    # Vacío = autodetectar por orden de keys presentes. Explicitarlo evita que
    # cargar una key para STT (ej. OpenAI) cambie de golpe el modelo del chat.
    default_llm_provider: str = ""

    # Defaults globales de providers (cada organización puede configurar el suyo)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    deepgram_api_key: str = ""
    openrouter_api_key: str = ""
    gmi_api_key: str = ""
    ollama_base_url: str = ""

    # Límites
    max_upload_mb: int = 500
    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 30

    @property
    def is_production(self) -> bool:
        return self.echo_env == "production"

    @property
    def superadmin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.superadmin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
