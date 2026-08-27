"""Hashing de contraseñas, JWT y cifrado de secretos en reposo."""
import base64
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

log = logging.getLogger("echo.security")

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ── JWT ──────────────────────────────────────────────────────────

def create_access_token(user_id: str, extra: dict | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Cifrado de secretos (API keys de providers) ──────────────────

def _fernet() -> Fernet:
    s = get_settings()
    if s.encryption_key:
        return Fernet(s.encryption_key.encode())
    if s.is_production:
        raise RuntimeError("ENCRYPTION_KEY es obligatoria en producción")
    log.warning("ENCRYPTION_KEY vacía: derivando clave de desarrollo del JWT_SECRET")
    derived = hashlib.sha256(("echo-dev-fernet:" + s.jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return None


def mask_secret(plaintext: str) -> str:
    """sk-abc...xyz — nunca devolver la key completa al frontend."""
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    return f"{plaintext[:4]}…{plaintext[-4:]}"
