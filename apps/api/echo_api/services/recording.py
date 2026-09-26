"""Grabación del audio completo de una reunión: temporal en la VM, final en Drive.

Por defecto Echo NO guarda audio: lo transcribe y lo descarta. Grabar es una
opción explícita por reunión, y aun así el audio no se queda en el servidor:

1. Mientras se graba, el WebSocket en vivo (routers/live.py) agrega el mismo
   PCM16 mono 16 kHz que ya recibe para transcribir a `<id>.pcm`.
2. Al finalizar, `finalize_recording` lo pasa a mp3 (≈14 MB por hora de
   reunión), borra el PCM y lo sube al Drive personal de quien grabó. Subido,
   se borra el mp3.
3. Si esa persona no tiene Drive conectado (o Drive falla), el mp3 queda para
   descargar `recording_ttl_hours` y después `cleanup_recordings` lo borra.

Estados de `meeting.recording["status"]`: recording, processing, uploaded,
download, expired, discarded, empty, failed.
"""
import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Meeting
from .stt.channels import downmix, split_channels

log = logging.getLogger("echo.recording")

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # PCM16 mono
MP3_MIME = "audio/mpeg"
# Un PCM que no se toca hace este tiempo es de una reunión que nunca se
# finalizó (se cerró la pestaña y nadie volvió): se borra igual.
ORPHAN_PCM_HOURS = 24


def recordings_dir() -> Path:
    path = Path(get_settings().recordings_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pcm_path(meeting_id: uuid.UUID) -> Path:
    return recordings_dir() / f"{meeting_id}.pcm"


def mp3_path(meeting_id: uuid.UUID) -> Path:
    return recordings_dir() / f"{meeting_id}.mp3"


def is_enabled(recording: dict | None) -> bool:
    return bool(recording and recording.get("enabled"))


class PcmWriter:
    """Agrega el audio que llega por el WebSocket al archivo de la reunión.

    Siempre en mono: si viene estéreo (micrófono + sistema) se mezcla, que es
    lo que se quiere escuchar después.
    """

    def __init__(self, meeting_id: uuid.UUID):
        self._file = open(pcm_path(meeting_id), "ab")  # noqa: SIM115 - vive lo que dura el WS

    def write(self, pcm16: bytes, channels: int) -> None:
        if channels == 2:
            left, right = split_channels(pcm16)
            pcm16 = downmix(left, right)
        self._file.write(pcm16)

    def close(self) -> None:
        try:
            self._file.close()
        except OSError:
            pass


async def update_state(meeting_id: uuid.UUID, **changes) -> dict | None:
    """Mezcla `changes` en meeting.recording y lo guarda. Devuelve el estado nuevo."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return None
        state = {**(meeting.recording or {}), **changes}
        meeting.recording = state
        await db.commit()
        return state


async def _to_mp3(source: Path, target: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", str(source),
        "-codec:a", "libmp3lame", "-b:a", "32k", str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError((stderr or b"").decode(errors="ignore")[-300:] or "ffmpeg falló")


def _expires_at() -> str:
    hours = get_settings().recording_ttl_hours
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


async def finalize_recording(meeting_id: uuid.UUID) -> None:
    """Cierra la grabación: mp3, Drive de quien grabó o descarga temporal.

    Corre en segundo plano al finalizar la reunión, aparte del pipeline: tiene
    que andar aunque no haya transcript ni IA configurada.
    """
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or not is_enabled(meeting.recording):
            return

    source = pcm_path(meeting_id)
    if not source.exists() or source.stat().st_size == 0:
        source.unlink(missing_ok=True)
        await update_state(meeting_id, status="empty")
        return

    await update_state(meeting_id, status="processing")
    target = mp3_path(meeting_id)
    try:
        await _to_mp3(source, target)
    except Exception as exc:  # noqa: BLE001 - la falla queda en el estado
        log.warning("recording: no se pudo convertir %s: %s", meeting_id, exc)
        # El PCM se conserva para reintentar; la limpieza lo borra si nadie lo hace.
        await update_state(meeting_id, status="failed", error="No se pudo preparar el audio.")
        return
    duration = int(source.stat().st_size / BYTES_PER_SECOND)
    source.unlink(missing_ok=True)
    await update_state(
        meeting_id,
        status="download",
        duration_seconds=duration,
        size_bytes=target.stat().st_size,
        expires_at=_expires_at(),
        error=None,
    )
    await upload_to_drive(meeting_id)


async def upload_to_drive(meeting_id: uuid.UUID, user_id: uuid.UUID | None = None) -> dict | None:
    """Sube el mp3 al Drive de quien grabó (o de `user_id`) y lo borra de acá.

    Sin conexión a Drive no hace nada: el archivo sigue disponible para
    descargar hasta que venza. Una falla de Drive tampoco lo borra.
    """
    from .drive import DriveError, get_user_connection, upload_recording

    target = mp3_path(meeting_id)
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or not target.exists():
            return None
        owner = user_id or uuid.UUID((meeting.recording or {}).get("user_id") or str(meeting.created_by))
        connection = await get_user_connection(db, owner)
        if connection is None:
            return meeting.recording
        try:
            url = await upload_recording(db, connection, meeting, target)
        except DriveError as exc:
            connection.last_error = str(exc)
            await db.commit()
            return await update_state(meeting_id, error=str(exc))
        except Exception:  # noqa: BLE001 - nunca perder el archivo por una falla de Drive
            log.exception("recording: falla inesperada subiendo %s", meeting_id)
            return await update_state(meeting_id, error="No se pudo subir a Drive. Descargalo desde acá.")
        connection.last_error = None
        await db.commit()
    target.unlink(missing_ok=True)
    return await update_state(
        meeting_id, status="uploaded", drive_url=url, expires_at=None, error=None
    )


async def discard_file(meeting_id: uuid.UUID) -> dict | None:
    mp3_path(meeting_id).unlink(missing_ok=True)
    pcm_path(meeting_id).unlink(missing_ok=True)
    return await update_state(meeting_id, status="discarded", expires_at=None)


async def cleanup_recordings() -> int:
    """Borra lo vencido: mp3 pasado de plazo y PCM de reuniones abandonadas."""
    removed = 0
    now = datetime.now(UTC)
    folder = recordings_dir()
    mp3s: dict[uuid.UUID, Path] = {}
    for path in folder.iterdir():
        try:
            meeting_id = uuid.UUID(path.stem)
        except ValueError:
            continue
        if path.suffix == ".pcm":
            if time.time() - path.stat().st_mtime > ORPHAN_PCM_HOURS * 3600:
                path.unlink(missing_ok=True)
                removed += 1
        elif path.suffix == ".mp3":
            mp3s[meeting_id] = path
    if not mp3s:
        return removed

    async with SessionLocal() as db:
        rows = (await db.execute(select(Meeting).where(Meeting.id.in_(list(mp3s))))).scalars().all()
        by_id = {meeting.id: meeting for meeting in rows}
        for meeting_id, path in mp3s.items():
            meeting = by_id.get(meeting_id)
            expires = (meeting.recording or {}).get("expires_at") if meeting else None
            expired = True
            if expires:
                try:
                    expired = datetime.fromisoformat(expires) < now
                except ValueError:
                    expired = True
            elif meeting is not None:
                # Sin fecha: de una corrida vieja. Se mide por la edad del archivo.
                hours = get_settings().recording_ttl_hours
                expired = time.time() - path.stat().st_mtime > hours * 3600
            if not expired:
                continue
            path.unlink(missing_ok=True)
            removed += 1
            if meeting is not None:
                meeting.recording = {**(meeting.recording or {}), "status": "expired", "expires_at": None}
        await db.commit()
    return removed


async def cleanup_loop(interval_seconds: int = 1800) -> None:
    while True:
        try:
            removed = await cleanup_recordings()
            if removed:
                log.info("recording: %s archivos vencidos borrados", removed)
        except Exception:  # noqa: BLE001 - la limpieza nunca tira abajo la API
            log.exception("recording: falló la limpieza")
        await asyncio.sleep(interval_seconds)
