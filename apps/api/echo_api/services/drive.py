"""Actas y grabaciones a Google Drive.

Alcance pedido: `drive.file`. Echo solo ve y toca lo que él mismo creó, así
que no puede leer el Drive de la institución aunque quisiera. El permiso
amplio (`drive`) daría acceso a todo y exige revisión de Google; no vale la
pena para lo único que hace falta acá, que es escribir actas.

Estructura: una carpeta madre por organización; adentro, una por familia, y
adentro de cada familia una por reunión ("2026-10-21 — Motivo") con el acta y
la grabación. Todo se crea solo la primera vez que hace falta. La carpeta
madre se puede mover a cualquier lado del Drive (por ejemplo, adentro de una
carpeta compartida con todo el equipo): el acceso lo da haberla creado, no
dónde esté, y lo de adentro hereda con quién está compartida.

El acta sube apenas Echo la genera y se reemplaza en cada versión nueva
(editada, aprobada): un solo archivo por reunión, siempre el último.
"""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Family,
    Meeting,
    MeetingReason,
    Minutes,
    MinutesVersion,
    OrgGoogleDrive,
    Organization,
    UserGoogleDrive,
)
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


_locks: dict[str, asyncio.Lock] = {}


def _lock(key: str) -> asyncio.Lock:
    """Un lock por carpeta: el acta y la grabación llegan casi juntas y sin
    esto cada una crearía su propia carpeta de la reunión (o de la familia).
    Alcanza en memoria porque la API corre en un solo proceso."""
    return _locks.setdefault(key, asyncio.Lock())


async def ensure_root_folder(db: AsyncSession, connection: OrgGoogleDrive) -> str:
    """Devuelve el id de la carpeta madre, creándola si hace falta."""
    async with _lock(f"root:{connection.organization_id}"):
        await db.refresh(connection, ["root_folder_id", "root_folder_url"])
        if connection.root_folder_id:
            return connection.root_folder_id

        org = await db.get(Organization, connection.organization_id)
        token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
        created = await _create_folder(token, f"Echo — {org.name if org else 'Actas'}")
        connection.root_folder_id = created["id"]
        connection.root_folder_url = created.get("webViewLink")
        await db.commit()
        return connection.root_folder_id


def _safe(name: str, limit: int = 80) -> str:
    return " ".join(name.replace("/", "-").split())[:limit]


async def _ensure_family_folder(
    db: AsyncSession, connection: OrgGoogleDrive, token: str, family: Family | None
) -> str:
    """Carpeta de la familia dentro de la madre. Sin familia, va a la madre."""
    root = await ensure_root_folder(db, connection)
    if family is None:
        return root
    async with _lock(f"family:{family.id}"):
        await db.refresh(family, ["drive_folder_id", "drive_url"])
        if family.drive_folder_id:
            return family.drive_folder_id
        created = await _create_folder(token, _safe(family.name, 120), parent=root)
        family.drive_folder_id = created["id"]
        # El enlace de la familia, si nadie puso otro a mano.
        if not family.drive_url:
            family.drive_url = created.get("webViewLink") or f"https://drive.google.com/drive/folders/{created['id']}"
        await db.commit()
        return created["id"]


async def _meeting_folder_name(db: AsyncSession, meeting: Meeting) -> str:
    fecha = (meeting.started_at or meeting.created_at).strftime("%Y-%m-%d")
    reason = await db.get(MeetingReason, meeting.reason_id) if meeting.reason_id else None
    return f"{fecha} — {_safe(reason.name if reason else meeting.title)}"


async def _ensure_meeting_folder(
    db: AsyncSession, connection: OrgGoogleDrive, token: str, meeting: Meeting
) -> str:
    """Carpeta "fecha — motivo" de la reunión, dentro de la de su familia."""
    async with _lock(f"meeting:{meeting.id}"):
        await db.refresh(meeting, ["drive_folder_id"])
        if meeting.drive_folder_id:
            return meeting.drive_folder_id
        family = await db.get(Family, meeting.family_id) if meeting.family_id else None
        parent = await _ensure_family_folder(db, connection, token, family)
        created = await _create_folder(token, await _meeting_folder_name(db, meeting), parent=parent)
        meeting.drive_folder_id = created["id"]
        await db.commit()
        return created["id"]


async def _get_file(token: str, file_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{FILES_URL}/{file_id}",
            params={"supportsAllDrives": "true", "fields": "id,parents,trashed"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise DriveError(_friendly(response.status_code, response.text))
    return response.json()


async def _update_file(token: str, file_id: str, name: str, blob: bytes, mime: str) -> dict | None:
    """Reemplaza el contenido (y el nombre) de un archivo. None si ya no existe."""
    files = {
        "metadata": ("metadata", json.dumps({"name": name}), "application/json; charset=UTF-8"),
        "file": (name, blob, mime),
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.patch(
            f"{UPLOAD_URL}/{file_id}",
            params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink,trashed"},
            headers={"Authorization": f"Bearer {token}"},
            files=files,
        )
    if response.status_code == 404:
        return None
    if response.status_code not in (200, 201):
        raise DriveError(_friendly(response.status_code, response.text))
    data = response.json()
    return None if data.get("trashed") else data


async def upload_minutes(meeting_id: uuid.UUID) -> None:
    """Sube (o reemplaza) el acta de una reunión en el Drive de la sede.

    Corre como tarea de fondo: cualquier falla se guarda en last_error, porque
    si no una integración rota es invisible hasta que alguien va a buscar un
    acta a Drive y no está.
    """
    from ..db import SessionLocal
    from ..routers.exports import _font_of, _markdown_to_docx

    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting or meeting.deleted_at is not None:
            return
        # Las internas (directivos, DOE...) no van a la carpeta compartida.
        if meeting.kind == "interna":
            return
        connection = await get_connection(db, meeting.organization_id)
        if not connection:
            return

        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if not minutes or not minutes.current_version:
            return
        # Ya está subida esta misma versión: no duplicar el archivo.
        if minutes.drive_synced_version == minutes.current_version and minutes.drive_file_id:
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
            parent = await _ensure_meeting_folder(db, connection, token, meeting)

            name = f"Acta {await _meeting_folder_name(db, meeting)}.docx"
            org = await db.get(Organization, meeting.organization_id)
            blob = _markdown_to_docx(version.body_markdown, meeting.title, _font_of(org)[0])
            created = None
            if minutes.drive_file_id:
                created = await _update_file(token, minutes.drive_file_id, name, blob, DOCX_MIME)
            if created is None:
                created = await _upload(token, name, parent, blob, DOCX_MIME)

            minutes.drive_file_id = created["id"]
            minutes.drive_file_url = created.get("webViewLink")
            minutes.drive_synced_version = version.version
            connection.last_error = None
            await db.commit()
            log.info("drive: acta de %s subida (v%s)", meeting_id, version.version)
        except DriveError as exc:
            connection.last_error = str(exc)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - nunca romper el flujo del acta
            log.exception("drive: falla inesperada subiendo el acta de %s", meeting_id)
            connection.last_error = "No se pudo guardar el acta en Drive."
            await db.commit()
            del exc


async def upload_recording_to_org(db: AsyncSession, connection: OrgGoogleDrive, meeting: Meeting, path) -> str:
    """Sube el mp3 a la carpeta de la reunión en el Drive de la sede."""
    token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
    parent = await _ensure_meeting_folder(db, connection, token, meeting)
    name = f"Grabación {await _meeting_folder_name(db, meeting)}.mp3"
    created = await _upload_resumable(token, name, parent, path, "audio/mpeg")
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"


async def sync_meeting_folder(meeting_id: uuid.UUID) -> None:
    """Si a la reunión le cambiaron la familia o el motivo, mueve y renombra su carpeta."""
    from ..db import SessionLocal

    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting or not meeting.drive_folder_id:
            return
        connection = await get_connection(db, meeting.organization_id)
        if not connection:
            return
        try:
            token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
            current = await _get_file(token, meeting.drive_folder_id)
            if current is None or current.get("trashed"):
                meeting.drive_folder_id = None
                await db.commit()
                return
            family = await db.get(Family, meeting.family_id) if meeting.family_id else None
            parent = await _ensure_family_folder(db, connection, token, family)
            old_parents = ",".join(p for p in current.get("parents", []) if p != parent)
            params = {"supportsAllDrives": "true", "fields": "id"}
            if old_parents:
                params["addParents"] = parent
                params["removeParents"] = old_parents
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.patch(
                    f"{FILES_URL}/{meeting.drive_folder_id}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": await _meeting_folder_name(db, meeting)},
                )
            if response.status_code not in (200, 201):
                raise DriveError(_friendly(response.status_code, response.text))
        except DriveError as exc:
            connection.last_error = str(exc)
            await db.commit()
        except Exception:  # noqa: BLE001 - mover la carpeta nunca rompe la clasificación
            log.exception("drive: no se pudo mover la carpeta de %s", meeting_id)


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


# ── Drive personal (grabaciones) ─────────────────────────────────

RECORDINGS_FOLDER = "Echo — Grabaciones"
# Trozos de la subida reanudable: múltiplos de 256 KiB, como pide Google.
UPLOAD_CHUNK = 8 * 256 * 1024


async def get_user_connection(db: AsyncSession, user_id: uuid.UUID) -> UserGoogleDrive | None:
    return (
        await db.execute(select(UserGoogleDrive).where(UserGoogleDrive.user_id == user_id))
    ).scalar_one_or_none()


async def save_user_connection(
    db: AsyncSession, user_id: uuid.UUID, refresh_token_enc: str, email: str | None
) -> UserGoogleDrive:
    connection = await get_user_connection(db, user_id)
    if connection is None:
        connection = UserGoogleDrive(user_id=user_id, refresh_token_enc=refresh_token_enc)
        db.add(connection)
    else:
        connection.refresh_token_enc = refresh_token_enc
        # Otra cuenta puede no ver la carpeta vieja: se crea una nueva.
        if email != connection.connected_email:
            connection.folder_id = None
            connection.folder_url = None
    connection.connected_email = email
    connection.connected_at = datetime.now(UTC)
    connection.last_error = None
    await db.commit()
    return connection


async def _ensure_user_folder(db: AsyncSession, connection: UserGoogleDrive, token: str) -> str:
    if connection.folder_id:
        return connection.folder_id
    created = await _create_folder(token, RECORDINGS_FOLDER)
    connection.folder_id = created["id"]
    connection.folder_url = created.get("webViewLink")
    await db.commit()
    return connection.folder_id


async def _upload_resumable(token: str, name: str, parent: str, path, mime: str) -> dict:
    """Subida reanudable leyendo el archivo de a trozos: nunca entero en memoria."""
    size = path.stat().st_size
    async with httpx.AsyncClient(timeout=120) as client:
        start = await client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "supportsAllDrives": "true", "fields": "id,webViewLink"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Upload-Content-Type": mime,
                "X-Upload-Content-Length": str(size),
            },
            json={"name": name, "parents": [parent]},
        )
        if start.status_code != 200 or "location" not in start.headers:
            raise DriveError(_friendly(start.status_code, start.text))
        session_url = start.headers["location"]

        offset = 0
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(UPLOAD_CHUNK)
                end = offset + len(chunk) - 1
                response = await client.put(
                    session_url,
                    content=chunk,
                    headers={"Content-Range": f"bytes {offset}-{end}/{size}" if chunk else f"bytes */{size}"},
                )
                offset += len(chunk)
                if response.status_code in (200, 201):
                    return response.json()
                if response.status_code != 308:
                    raise DriveError(_friendly(response.status_code, response.text))
                if not chunk:
                    raise DriveError("Drive no confirmó la subida del audio.")


async def upload_recording(db: AsyncSession, connection: UserGoogleDrive, meeting: Meeting, path) -> str:
    """Sube el mp3 de la reunión a la carpeta de grabaciones de la persona."""
    token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
    parent = await _ensure_user_folder(db, connection, token)
    fecha = (meeting.started_at or meeting.created_at).strftime("%Y-%m-%d")
    safe_title = meeting.title[:80].replace("/", "-")
    created = await _upload_resumable(token, f"{fecha} — {safe_title}.mp3", parent, path, "audio/mpeg")
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"


DOCS_FOLDER = "Echo — Documentos"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


async def _find_or_create_docs_folder(token: str) -> str:
    """Carpeta de los documentos exportados. Con drive.file solo se ven las creadas por Echo."""
    async with httpx.AsyncClient(timeout=30) as client:
        found = await client.get(
            FILES_URL,
            params={
                "q": f"name = '{DOCS_FOLDER}' and mimeType = '{FOLDER_MIME}' and trashed = false",
                "fields": "files(id)",
                "pageSize": "1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    if found.status_code == 200 and found.json().get("files"):
        return found.json()["files"][0]["id"]
    return (await _create_folder(token, DOCS_FOLDER))["id"]


async def upload_google_doc(db: AsyncSession, connection: UserGoogleDrive, name: str, docx: bytes) -> str:
    """Sube un .docx a Drive y Google lo convierte en Documento de Google editable."""
    try:
        token = await _access_token(decrypt_secret(connection.refresh_token_enc) or "")
        parent = await _find_or_create_docs_folder(token)
        metadata = {"name": name, "parents": [parent], "mimeType": GOOGLE_DOC_MIME}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                UPLOAD_URL,
                params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"},
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (name, docx, DOCX_MIME),
                },
            )
        if response.status_code not in (200, 201):
            raise DriveError(_friendly(response.status_code, response.text))
    except DriveError as exc:
        connection.last_error = str(exc)
        await db.commit()
        raise
    connection.last_error = None
    await db.commit()
    created = response.json()
    return created.get("webViewLink") or f"https://docs.google.com/document/d/{created['id']}/edit"
