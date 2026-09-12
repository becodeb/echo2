"""Arranque seguro: secretos de producción y fallos que no se tragan.

Estos tests existen por tres bugs concretos que no se veían desde afuera: un
JWT_SECRET vacío firmaba tokens igual, una ENCRYPTION_KEY faltante se reportaba
como "no hay API key configurada", y un hash corrupto en la base era
indistinguible de una contraseña mal tipeada. Los tres fallaban en silencio, así
que lo que se prueba acá es justamente que ahora hagan ruido.
"""
import logging

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from echo_api.config import INSECURE_JWT_SECRET, MIN_JWT_SECRET_CHARS, Settings
from echo_api.security import decrypt_secret, encrypt_secret, hash_password, verify_password

# Generada, no escrita a mano: una constante pegada acá se vuelve un segundo
# formato que mantener cada vez que cambie el de Fernet.
VALID_FERNET_KEY = Fernet.generate_key().decode()
STRONG_SECRET = "s" * MIN_JWT_SECRET_CHARS


def _production(**overrides) -> Settings:
    """Settings de producción con todo sano, salvo lo que el test rompa."""
    base = {
        "echo_env": "production",
        "jwt_secret": STRONG_SECRET,
        "encryption_key": VALID_FERNET_KEY,
    }
    base.update(overrides)
    return Settings(**base)


# ── JWT_SECRET ───────────────────────────────────────────────────

def test_production_rejects_empty_jwt_secret():
    with pytest.raises(ValidationError) as error:
        _production(jwt_secret="")
    assert "JWT_SECRET" in str(error.value)


def test_production_rejects_default_jwt_secret():
    """El default está en el repo: es tan público como no tener secreto."""
    with pytest.raises(ValidationError) as error:
        _production(jwt_secret=INSECURE_JWT_SECRET)
    assert "JWT_SECRET" in str(error.value)


def test_production_rejects_short_jwt_secret():
    with pytest.raises(ValidationError) as error:
        _production(jwt_secret="a" * (MIN_JWT_SECRET_CHARS - 1))
    assert "JWT_SECRET" in str(error.value)


def test_production_error_says_how_to_generate_the_secret():
    """Un error de arranque sin la receta al lado sólo mueve el problema."""
    with pytest.raises(ValidationError) as error:
        _production(jwt_secret="")
    assert "secrets.token_urlsafe" in str(error.value)


# ── ENCRYPTION_KEY ───────────────────────────────────────────────

def test_production_rejects_empty_encryption_key():
    with pytest.raises(ValidationError) as error:
        _production(encryption_key="")
    assert "ENCRYPTION_KEY" in str(error.value)


def test_production_rejects_malformed_encryption_key():
    """Una clave mal pegada tiene que costar un arranque, no seis horas."""
    with pytest.raises(ValidationError) as error:
        _production(encryption_key="esto-no-es-una-clave-fernet")
    assert "ENCRYPTION_KEY" in str(error.value)


def test_production_error_says_how_to_generate_the_encryption_key():
    with pytest.raises(ValidationError) as error:
        _production(encryption_key="")
    assert "Fernet.generate_key" in str(error.value)


def test_production_reports_every_problem_at_once():
    """Arreglar un secreto y volver a chocar con el otro es un viaje de más."""
    with pytest.raises(ValidationError) as error:
        _production(jwt_secret="", encryption_key="")
    message = str(error.value)
    assert "JWT_SECRET" in message and "ENCRYPTION_KEY" in message


def test_production_accepts_sane_secrets():
    settings = _production()
    assert settings.is_production


# ── Desarrollo: avisa, no bloquea ────────────────────────────────

def test_development_still_builds_with_insecure_defaults(caplog):
    with caplog.at_level(logging.WARNING, logger="echo.config"):
        settings = Settings(
            echo_env="development", jwt_secret=INSECURE_JWT_SECRET, encryption_key=""
        )
    assert settings.jwt_secret == INSECURE_JWT_SECRET
    assert not settings.is_production
    assert any("JWT_SECRET" in record.message for record in caplog.records)


def test_test_env_still_builds_with_insecure_defaults():
    """La suite entera corre con ECHO_ENV=test: no puede exigir secretos."""
    assert Settings(echo_env="test", jwt_secret="", encryption_key="").echo_env == "test"


# ── decrypt_secret: None significa sólo una cosa ─────────────────

def test_decrypt_secret_returns_none_for_corrupted_ciphertext():
    token = encrypt_secret("sk-de-mentira")
    assert decrypt_secret(token[:-6] + "AAAAAA") is None


def test_decrypt_secret_returns_none_for_garbage():
    assert decrypt_secret("esto-no-es-un-token") is None


def test_decrypt_secret_roundtrip_still_works():
    assert decrypt_secret(encrypt_secret("sk-de-mentira")) == "sk-de-mentira"


# ── verify_password: el fallo raro deja rastro ───────────────────

def test_verify_password_accepts_the_right_one():
    assert verify_password("supersegura123", hash_password("supersegura123"))


def test_wrong_password_is_silent(caplog):
    hashed = hash_password("supersegura123")
    with caplog.at_level(logging.WARNING, logger="echo.security"):
        assert verify_password("otra-cosa", hashed) is False
    assert caplog.records == []


def test_corrupted_hash_returns_false_but_warns(caplog):
    """Un hash ilegible es un incidente de datos, no un login fallido."""
    with caplog.at_level(logging.WARNING, logger="echo.security"):
        assert verify_password("supersegura123", "$argon2id$roto") is False
    assert any("hash" in record.message for record in caplog.records)
