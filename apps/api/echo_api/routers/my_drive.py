"""Drive personal: adonde van las grabaciones de cada persona.

Mismo flujo que el Drive de la organización (routers/drive.py), y el mismo
callback de Google: el estado firmado dice que es personal. Cualquier persona
puede conectar el suyo; no hace falta ser admin porque los archivos son suyos.
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..security import create_access_token
from ..services.drive import DRIVE_SCOPE, get_user_connection
from .drive import AUTHORIZE_URL, STATE_COOKIE, STATE_PATH, _callback_url

router = APIRouter(prefix="/api/me/drive", tags=["drive"])


class MyDriveOut(BaseModel):
    enabled: bool
    connected: bool
    connected_email: str | None = None
    folder_url: str | None = None
    last_error: str | None = None


@router.get("", response_model=MyDriveOut)
async def my_drive(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    connection = await get_user_connection(db, user.id)
    return MyDriveOut(
        enabled=get_settings().google_enabled,
        connected=connection is not None,
        connected_email=connection.connected_email if connection else None,
        folder_url=connection.folder_url if connection else None,
        last_error=connection.last_error if connection else None,
    )


@router.post("/connect-url")
async def my_drive_connect_url(user: User = Depends(get_current_user)):
    settings = get_settings()
    if not settings.google_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Google no está configurado en el servidor")
    state = create_access_token(str(user.id), extra={"purpose": "drive_user"})
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _callback_url(),
        "response_type": "code",
        "scope": f"openid email {DRIVE_SCOPE}",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "login_hint": user.email,
    }
    response = JSONResponse({"url": f"{AUTHORIZE_URL}?{urlencode(params)}"})
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=STATE_PATH,
    )
    return response


@router.delete("", status_code=204)
async def my_drive_disconnect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    connection = await get_user_connection(db, user.id)
    if connection is not None:
        # Se borra el token, no los archivos: lo que ya está en Drive es de la persona.
        await db.delete(connection)
        await db.commit()
