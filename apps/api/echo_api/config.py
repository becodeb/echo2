"""Configuración central del API de Echo (pydantic-settings)."""
import logging
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("echo.config")

# Valor de fábrica del jwt_secret. Está acá arriba y no escondido en el campo
# porque la validación de arranque necesita reconocerlo: un secreto que sigue
# siendo el de fábrica es exactamente igual de público que no tener ninguno.
INSECURE_JWT_SECRET = "dev_only_insecure_secret_change_me"

# 32 caracteres es el piso, no el ideal. HS256 usa la clave tal cual: una
# passphrase corta se rompe offline con un diccionario sobre cualquier token
# emitido, y un token forjado vale tanto como el `sub` que el atacante elija.
MIN_JWT_SECRET_CHARS = 32

_GENERATE_JWT_SECRET = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'
_GENERATE_ENCRYPTION_KEY = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


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
    # Modelo del default del servidor. Vacío = el que Echo trae por proveedor.
    # Existe para poder apuntar a un modelo gratuito (por ejemplo uno ":free"
    # de OpenRouter) sin tocar código: el default del servidor es lo que usa
    # toda organización que no configuró el suyo.
    default_llm_model: str = ""

    # Defaults globales de providers (cada organización puede configurar el suyo)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    deepgram_api_key: str = ""
    openrouter_api_key: str = ""
    orcarouter_api_key: str = ""
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

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        """Impide que la app arranque en producción con secretos de juguete.

        La alternativa —que es lo que pasaba antes— es peor que un arranque
        fallido: sin JWT_SECRET la app firma HS256 con clave vacía y cualquiera
        se emite un access token con el `sub` que quiera, pero todo *parece*
        funcionar. Un fallo de arranque lo ve el que despliega; una clave vacía
        no la ve nadie hasta que es tarde.

        ENCRYPTION_KEY se valida acá y no en el primer uso por la misma razón
        temporal: una clave mal pegada tiene que costar un arranque, no seis
        horas de API keys que se descifran mal en producción.

        En desarrollo nada de esto bloquea: se avisa por log y se sigue, para
        no pedirle ceremonia a quien recién clona el repo.
        """
        problems: list[str] = []

        if self.is_production:
            if not self.jwt_secret:
                problems.append(
                    "JWT_SECRET está vacía. Generala con: " + _GENERATE_JWT_SECRET
                )
            elif self.jwt_secret == INSECURE_JWT_SECRET:
                problems.append(
                    "JWT_SECRET sigue siendo el valor de desarrollo, que es público. "
                    "Generá una propia con: " + _GENERATE_JWT_SECRET
                )
            elif len(self.jwt_secret) < MIN_JWT_SECRET_CHARS:
                problems.append(
                    f"JWT_SECRET tiene {len(self.jwt_secret)} caracteres y el mínimo es "
                    f"{MIN_JWT_SECRET_CHARS}. Generá una más larga con: "
                    + _GENERATE_JWT_SECRET
                )

            if not self.encryption_key:
                problems.append(
                    "ENCRYPTION_KEY está vacía y es obligatoria en producción. "
                    "Generala con: " + _GENERATE_ENCRYPTION_KEY
                )
            else:
                try:
                    Fernet(self.encryption_key.encode())
                except Exception:
                    problems.append(
                        "ENCRYPTION_KEY no es una clave Fernet válida (se esperan 32 bytes "
                        "en base64 urlsafe). Generá una con: " + _GENERATE_ENCRYPTION_KEY
                    )

            if problems:
                raise ValueError(
                    "Configuración insegura para ECHO_ENV=production:\n  - "
                    + "\n  - ".join(problems)
                )
            return self

        # Fuera de producción alcanza con dejar rastro en el log.
        if not self.jwt_secret or self.jwt_secret == INSECURE_JWT_SECRET:
            log.warning(
                "JWT_SECRET es el valor de desarrollo: sirve para probar, no para desplegar"
            )
        if not self.encryption_key:
            log.warning(
                "ENCRYPTION_KEY vacía: se derivará una clave de desarrollo del JWT_SECRET"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
