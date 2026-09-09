"""Subida de actas a Google Drive.

Alcance pedido: `drive.file`. Echo solo ve y toca lo que él mismo creó, así
que no puede leer el Drive de la institución aunque quisiera. El permiso
amplio (`drive`) daría acceso a todo y exige revisión de Google; no vale la
pena para lo único que hace falta acá, que es escribir actas.

Estructura: una carpeta madre por organización, y adentro una subcarpeta por
familia que se crea sola la primera vez que hace falta. La carpeta madre se
puede mover a cualquier lado del Drive — el acceso lo da haberla creado, no
dónde esté.
"""
import json
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Family, Meeting, Minutes, MinutesVersion, OrgGoogleDrive, Organization
from ..security import decrypt_secret

log = logging.getLogger("echo.drive")

TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Alcance mínimo. Está acá y no en config porque no es configurable: pedir más
# cambiaría el trato con el usuario y tiene que ser una decisión de código.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveError(Exception):
    """Falla al hablar con Drive. El mensaje ya viene apto para mostrar."""


def _friendly(status_code: int, body: str) -> str:
    if status_code in (401, 403):
        return (
            "Google rechazó la conexión con Drive. Volvé a conectar la cuenta "
            "en Ajustes → Google Drive."
        )
    if status_code == 404:
        return "La carpeta de Drive ya no existe. Volvé a conectar la cuenta."
    if status_code == 429:
        return "Google está limitando las solicitudes. Se reintenta en la próxima acta."
    log.warning("drive: respuesta inesperada %s: %s", status_code, body[:300])
    return "No se pudo guardar el acta en Drive. Probá de nuevo en un momento."


async def _access_token(refresh_token: str) -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise DriveError(_friendly(response.status_code, response.text))
    token = response.json().get("access_token")
    if not token:
        raise DriveError("Google no devolvió un token de acceso.")
    return token


async def _create_folder(token: str, name: str, parent: str | None = None) -> dict:
    body: dict = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        body["parents"] = [parent]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            FILES_URL,
            params={"supportsAllDrives": "true", "fields": "id,webViewLink"},
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
    if response.status_code not in (200, 201):
        raise DriveError(_friendly(response.status_code, response.text))
    return response.json()


async def _upload(token: str, name: str, parent: str, blob: bytes, mime: str) -> dict:
    metadata = {"name": name, "parents": [parent]}
    files = {
        "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
        "file": (name, blob, mime),
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            UPLOAD_URL,
            params={
                "uploadType": "multipart",
                "supportsAllDrives": "true",
                "fields": "id,webViewLink",
            },
            headers={"Authorization": f"Bearer {token}"},
            files=files,
        )
    if response.status_code not in (200, 201):
        raise DriveError(_friendly(response.status_code, response.text))
    return response.json()


async def get_connection(db: AsyncSession, org_id: uuid.UUID) -> OrgGoogleDrive | None:
    return (
        await db.execute(
            select(OrgGoogleDrive).where(OrgGoogleDrive.organization_id == org_id)
        )
    ).scalar_one_or_none()


async def ensure_root_folder(db: AsyncSession, connection: OrgGoogleDrive) -> str:
    """Devuelve el id de la carpeta madre, creándola si hace falta."""
    if connection.root_folder_id:
        return connection.root_folder_id

    org = await db.get(Organization, connection.organization_id)
    token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
    created = await _create_folder(token, f"Echo — {org.name if org else 'Actas'}")
    connection.root_folder_id = created["id"]
    connection.root_folder_url = created.get("webViewLink")
    await db.commit()
    return connection.root_folder_id


async def _ensure_family_folder(
    db: AsyncSession, connection: OrgGoogleDrive, token: str, family: Family | None
) -> str:
    """Carpeta de la familia dentro de la madre. Sin familia, va a la madre."""
    root = await ensure_root_folder(db, connection)
    if family is None:
        return root

    # Si la familia ya tiene carpeta creada por Echo, se reutiliza. El
    # drive_url puede haberlo puesto una persona a mano apuntando a otra
    # carpeta: en ese caso no se toca y el acta va a la madre, porque sobre
    # una carpeta ajena `drive.file` no da permiso de escritura.
    if family.drive_url and "/folders/" in family.drive_url:
        folder_id = family.drive_url.rsplit("/folders/", 1)[1].split("?")[0]
        if folder_id:
            return folder_id

    created = await _create_folder(token, family.name, parent=root)
    family.drive_url = created.get("webViewLink") or f"https://drive.google.com/drive/folders/{created['id']}"
    await db.commit()
    return created["id"]


async def upload_minutes(meeting_id: uuid.UUID) -> None:
    """Sube el acta aprobada de una reunión a Drive.

    Corre como tarea de fondo: cualquier falla se guarda en last_error, porque
    si no una integración rota es invisible hasta que alguien va a buscar un
    acta a Drive y no está.
    """
    from ..db import SessionLocal
    from ..routers.exports import _markdown_to_docx

    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        connection = await get_connection(db, meeting.organization_id)
        if not connection:
            return

        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if not minutes or minutes.status != "approved":
            return
        # Ya está subida esta misma versión: no duplicar el archivo.
        if minutes.drive_synced_version == minutes.current_version:
            return

        version = (
            await db.execute(
                select(MinutesVersion).where(
                    MinutesVersion.minutes_id == minutes.id,
                    MinutesVersion.version == minutes.current_version,
                )
            )
        ).scalar_one_or_none()
        if not version:
            return

        try:
            token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
            family = await db.get(Family, meeting.family_id) if meeting.family_id else None
            parent = await _ensure_family_folder(db, connection, token, family)

            fecha = (meeting.started_at or meeting.created_at).strftime("%Y-%m-%d")
            safe_title = meeting.title[:60].replace("/", "-")
            name = f"{fecha} — {safe_title} (v{version.version}).docx"
            blob = _markdown_to_docx(version.body_markdown, meeting.title)
            created = await _upload(token, name, parent, blob, DOCX_MIME)

            minutes.drive_file_url = created.get("webViewLink")
            minutes.drive_synced_version = minutes.current_version
            connection.last_error = None
            await db.commit()
            log.info("drive: acta de %s subida", meeting_id)
        except DriveError as exc:
            connection.last_error = str(exc)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - nunca romper el flujo del acta
            log.exception("drive: falla inesperada subiendo el acta de %s", meeting_id)
            connection.last_error = "No se pudo guardar el acta en Drive."
            await db.commit()
            del exc


async def save_connection(
    db: AsyncSession,
    org_id: uuid.UUID,
    refresh_token_enc: str,
    email: str | None,
    user_id: uuid.UUID,
) -> OrgGoogleDrive:
    connection = await get_connection(db, org_id)
    if connection is None:
        connection = OrgGoogleDrive(organization_id=org_id, refresh_token_enc=refresh_token_enc)
        db.add(connection)
    else:
        connection.refresh_token_enc = refresh_token_enc
    connection.connected_email = email
    connection.connected_by = user_id
    connection.connected_at = datetime.now(UTC)
    connection.last_error = None
    await db.commit()
    return connection
