"""Conectar la organización con Google Drive.

El flujo no puede ser una llamada normal del SPA: Google devuelve al navegador
con una redirección de nivel superior, donde no viaja el header Authorization.
Por eso son dos pasos: el SPA pide la URL (autenticado, con su organización) y
recibe una cookie de estado firmada; después navega a Google, que vuelve al
callback con esa cookie y ahí se sabe quién y para qué organización era.
"""
import base64
import binascii
import json
import logging
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import OrganizationMember
from ..security import create_access_token, decode_token, encrypt_secret
from ..services.audit import audit
from ..services.drive import DRIVE_SCOPE, ensure_root_folder, get_connection

log = logging.getLogger("echo.drive")

router = APIRouter(prefix="/api/org/drive", tags=["drive"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "echo_drive_state"
STATE_PATH = "/api/org/drive"


def _callback_url() -> str:
    return get_settings().api_public_url.rstrip("/") + "/api/org/drive/callback"


def _web(path: str) -> str:
    return get_settings().web_origin.rstrip("/") + path


class DriveStatusOut(BaseModel):
    enabled: bool
    connected: bool
    connected_email: str | None = None
    root_folder_url: str | None = None
    last_error: str | None = None


class ConnectUrlOut(BaseModel):
    url: str


@router.get("/status", response_model=DriveStatusOut)
async def drive_status(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    settings = get_settings()
    connection = await get_connection(db, ctx.org_id)
    return DriveStatusOut(
        enabled=settings.google_enabled,
        connected=connection is not None,
        connected_email=connection.connected_email if connection else None,
        root_folder_url=connection.root_folder_url if connection else None,
        last_error=connection.last_error if connection else None,
    )


@router.post("/connect-url", response_model=ConnectUrlOut)
async def connect_url(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    settings = get_settings()
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Google no está configurado en el servidor")
    ctx.require_role("admin")

    # El estado es un JWT corto: identifica usuario y organización en el
    # callback, donde no hay sesión de la que colgarse.
    state = create_access_token(
        str(ctx.user.id), extra={"drive_org": str(ctx.org_id), "purpose": "drive"}
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _callback_url(),
        "response_type": "code",
        "scope": f"openid email {DRIVE_SCOPE}",
        "state": state,
        # offline + consent: sin los dos, Google no manda refresh token en las
        # reconexiones y la integración se cae sola al vencer el access token.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    response = ConnectUrlOut(url=f"{AUTHORIZE_URL}?{urlencode(params)}")
    from fastapi.responses import JSONResponse

    json_response = JSONResponse(response.model_dump())
    json_response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=STATE_PATH,
    )
    return json_response


def _decode_id_token(id_token: str) -> dict:
    parts = id_token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}


def _back(reason: str | None = None) -> RedirectResponse:
    path = "/settings/drive" + (f"?error={reason}" if reason else "?connected=1")
    response = RedirectResponse(_web(path), status_code=303)
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return response


@router.get("/callback")
async def drive_callback(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if request.query_params.get("error"):
        return _back("cancelado")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not code or not state or state != cookie_state:
        return _back("estado")

    payload = decode_token(state)
    if not payload or payload.get("purpose") != "drive":
        return _back("estado")

    try:
        user_id = uuid.UUID(payload["sub"])
        org_id = uuid.UUID(payload["drive_org"])
    except (KeyError, ValueError):
        return _back("estado")

    # La membresía se revalida acá: entre que se pidió la URL y volvió Google
    # pudieron sacar a la persona de la organización.
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.role.in_(("owner", "admin")),
            )
        )
    ).scalar_one_or_none()
    if not member:
        return _back("permisos")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": _callback_url(),
                    "grant_type": "authorization_code",
                },
            )
    except httpx.HTTPError:
        return _back("google")

    if token_response.status_code != 200:
        log.warning("drive: canje de code fallido (%s)", token_response.status_code)
        return _back("google")

    data = token_response.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        # Pasa cuando la cuenta ya había autorizado antes sin prompt=consent.
        return _back("sin_refresh")

    claims = _decode_id_token(data.get("id_token") or "")

    from ..services.drive import save_connection

    connection = await save_connection(
        db, org_id, encrypt_secret(refresh_token), claims.get("email"), user_id
    )
    try:
        await ensure_root_folder(db, connection)
    except Exception:
        log.exception("drive: no se pudo crear la carpeta madre de %s", org_id)

    await audit(db, org_id, user_id, "drive.connect", "organization", str(org_id))
    await db.commit()
    return _back()


@router.delete("", status_code=204)
async def disconnect(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("admin")
    connection = await get_connection(db, ctx.org_id)
    if connection is not None:
        # Se borra el token, no la carpeta: los archivos que ya están en Drive
        # son de la institución y no los toca nadie desde acá.
        await db.delete(connection)
        await audit(
            db, ctx.org_id, ctx.user.id, "drive.disconnect", "organization", str(ctx.org_id)
        )
        await db.commit()
