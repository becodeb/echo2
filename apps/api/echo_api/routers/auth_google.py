"""Crear cuenta e iniciar sesión con Google (OAuth 2.0 + OpenID Connect).

Flujo:
  1. El navegador va a /api/auth/google/start.
  2. Redirigimos a Google con un `state` que también guardamos en una cookie
     httpOnly de corta vida (defensa contra CSRF en el callback).
  3. Google vuelve a /api/auth/google/callback con un `code`.
  4. Canjeamos el code por el id_token server-to-server y creamos o
     recuperamos el usuario.
  5. Dejamos la cookie de refresh y mandamos al usuario a la web. El front
     arranca llamando a /api/auth/refresh, así que la sesión ya está lista.

El id_token no se valida por firma a propósito: viene directo del endpoint
de tokens de Google sobre TLS, que es el caso en el que la propia
documentación de Google dice que alcanza con verificar los claims.
"""
import base64
import binascii
import json
import logging
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_db
from ..models import User
from ..services.audit import audit
from .auth import AVATAR_COLORS, _issue_refresh, _set_refresh_cookie

log = logging.getLogger("echo.auth.google")

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

STATE_COOKIE = "echo_oauth_state"
STATE_TTL_SECONDS = 600
STATE_PATH = "/api/auth/google"


def _web_url(settings: Settings, path: str) -> str:
    return settings.web_origin.rstrip("/") + path


def _back_to_login(settings: Settings, reason: str) -> RedirectResponse:
    """Vuelve al login con un motivo genérico.

    El motivo es una etiqueta corta que el front traduce a un mensaje para la
    persona; el detalle técnico del error queda solo en los logs del servidor.
    """
    response = RedirectResponse(_web_url(settings, f"/login?error={reason}"), status_code=303)
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return response


def _decode_id_token(id_token: str) -> dict | None:
    """Devuelve los claims del id_token, o None si viene mal formado."""
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def _claims_are_valid(claims: dict, settings: Settings) -> bool:
    if claims.get("iss") not in VALID_ISSUERS:
        return False
    if claims.get("aud") != settings.google_client_id:
        return False
    try:
        if float(claims.get("exp", 0)) < datetime.now(UTC).timestamp():
            return False
    except (TypeError, ValueError):
        return False
    if not claims.get("sub") or not claims.get("email"):
        return False
    # Google marca email_verified=False en cuentas de dominios delegados sin
    # verificar; ahí no podemos confiar en el email para unificar cuentas.
    return claims.get("email_verified") in (True, "true")


@router.get("/status")
async def google_status():
    """Le dice al front si mostrar el botón de Google."""
    return {"enabled": get_settings().google_enabled}


@router.get("/start")
async def google_start():
    settings = get_settings()
    if not settings.google_enabled:
        return _back_to_login(settings, "google_no_configurado")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=303)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=STATE_PATH,
    )
    return response


@router.get("/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.google_enabled:
        return _back_to_login(settings, "google_no_configurado")

    if request.query_params.get("error"):
        # El usuario cerró la pantalla de Google o rechazó los permisos.
        return _back_to_login(settings, "google_cancelado")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return _back_to_login(settings, "google_state")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_callback_url,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError:
        log.warning("google: no se pudo contactar el endpoint de tokens")
        return _back_to_login(settings, "google")

    if token_response.status_code != 200:
        log.warning("google: canje de code fallido (%s)", token_response.status_code)
        return _back_to_login(settings, "google")

    id_token = token_response.json().get("id_token")
    claims = _decode_id_token(id_token) if id_token else None
    if not claims or not _claims_are_valid(claims, settings):
        log.warning("google: id_token inválido o email sin verificar")
        return _back_to_login(settings, "google")

    email = str(claims["email"]).lower()
    sub = str(claims["sub"])

    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    created = False

    if user is None:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is not None:
            # Cuenta creada antes con email y contraseña: la vinculamos.
            user.google_sub = sub
        else:
            user = User(
                email=email,
                password_hash=None,
                google_sub=sub,
                name=(claims.get("name") or email.split("@")[0]).strip()[:200],
                avatar_color=secrets.choice(AVATAR_COLORS),
            )
            db.add(user)
            await db.flush()
            created = True

    if not user.is_active or user.deleted_at is not None:
        return _back_to_login(settings, "cuenta_deshabilitada")

    refresh = await _issue_refresh(db, user, request)
    await audit(
        db,
        None,
        user.id,
        "user.register" if created else "user.login",
        "user",
        str(user.id),
        detail={"provider": "google"},
    )
    await db.commit()

    response = RedirectResponse(_web_url(settings, "/"), status_code=303)
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    _set_refresh_cookie(response, refresh)
    return response
