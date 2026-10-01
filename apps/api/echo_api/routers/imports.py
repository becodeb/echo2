"""Importar una reunión ya grabada (MP3/WAV/M4A/WebM/MP4).

Privacy-first: el archivo subido se pasa a audio de trabajo y se borra en el
momento; el audio de trabajo se borra al terminar la pasada final, igual que
el de una reunión en vivo. Nunca se archiva el audio.
"""
import asyncio
import contextlib
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import get_meeting_or_404, get_org_context, OrgContext, require_paid
from ..models import Meeting
from ..services import plans
from ..services.ai_settings import resolve_stt
from ..services.audit import audit
from ..services.background import spawn
from ..services.live_bus import live_bus
from ..services.pipeline import run_finalize_pipeline
from ..services.recording import pcm_path

log = logging.getLogger("echo.imports")

router = APIRouter(prefix="/api/meetings", tags=["imports"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".flac"}

# Tamaño de cada lectura al volcar el upload a disco. 1 MiB es el equilibrio:
# lo bastante grande para no hacer miles de vueltas por un archivo de cientos
# de MB, y lo bastante chico para que el techo de RAM por request no dependa
# del tamaño del archivo sino de esta constante.
UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _spool_upload(file: UploadFile, extension: str, max_bytes: int) -> tuple[str, int]:
    """Vuelca el upload a un temporal contando bytes, abortando apenas se pasa.

    Nunca materializa el archivo entero en RAM. El `await file.read()` sin
    argumentos que había antes era inalcanzable por diseño: nginx acepta hasta
    `client_max_body_size 512m` (apps/web/nginx.conf), o sea que el proceso
    moría por OOM bastante antes de llegar a comparar el tamaño y responder
    el 413.

    Devuelve (ruta del temporal, bytes escritos). El temporal queda en manos
    del llamador: si algo falla acá, se borra antes de propagar.
    """
    settings = get_settings()
    total = 0
    handle = tempfile.NamedTemporaryFile(suffix=extension or ".bin", delete=False)
    try:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"El archivo supera el máximo de {settings.max_upload_mb} MB",
                )
            handle.write(chunk)
    except BaseException:
        # Incluye el 413 de arriba: un upload rechazado no deja restos.
        handle.close()
        _remove(handle.name)
        raise
    handle.close()
    return handle.name, total


def _remove(path: str | None) -> None:
    """Borra un temporal sin quejarse si ya no está."""
    if path:
        with contextlib.suppress(OSError):
            os.unlink(path)


@router.post("/{meeting_id}/import", status_code=202)
async def import_recording(
    meeting_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    settings = get_settings()
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if meeting.status not in ("draft",):
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se puede importar a una reunión nueva")

    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Formato no soportado: {extension}")

    require_paid(ctx, "Importar grabaciones")
    try:
        await plans.check_audio_month(db, ctx.org, ctx.user)
    except plans.LimitReached as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    stt_config = await resolve_stt(db, ctx.org_id)
    if stt_config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No hay motor de transcripción configurado (Ajustes → Speech-to-Text)",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    # Atajo: si el cliente ya declara un tamaño imposible, cortamos sin leer un
    # solo byte del cuerpo. Es SÓLO un atajo — el header lo escribe el cliente
    # y puede mentir; la defensa real es el conteo chunk a chunk de _spool_upload.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"El archivo supera el máximo de {settings.max_upload_mb} MB",
        )

    source_path, total_bytes = await _spool_upload(file, extension, max_bytes)

    try:
        meeting.status = "processing"
        meeting.audio_source = "import"
        meeting.processing_state = {"stage": "transcribing", "progress": 5}
        await audit(db, ctx.org_id, ctx.user.id, "meeting.import", "meeting", str(meeting.id),
                    detail={"filename": file.filename, "bytes": total_bytes})
        await db.commit()
    except BaseException:
        # Si la reunión no quedó marcada, nadie va a procesar ese temporal.
        _remove(source_path)
        raise

    # Se pasa la RUTA, no los bytes: mandar el buffer por valor a la tarea
    # duplicaba el pico de memoria justo cuando ya era el peor momento.
    spawn(
        _process_import(str(meeting.id), source_path),
        name=f"import:{meeting.id}",
    )
    return {"status": "processing"}


async def _process_import(meeting_id: str, source_path: str) -> None:
    """El audio importado pasa a ser el audio de trabajo de la reunión y la
    pasada final lo transcribe como a cualquier otra: Groq, o ElevenLabs con
    personas según el plan (con sus créditos y su consumo anotado). Después de
    procesar se borra (services/recording.py), igual que el de una reunión en vivo.
    """
    mid = uuid.UUID(meeting_id)
    target = pcm_path(mid)
    try:
        # PCM16 mono 16 kHz, lo que lee la pasada final. ffmpeg lee del disco:
        # nunca hace falta tener el archivo crudo en RAM.
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", source_path, "-ac", "1", "-ar", "16000", "-f", "s16le", str(target),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        if process.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise RuntimeError("No se pudo leer el audio. Probá con otro formato (mp3, m4a o wav).")

        async with SessionLocal() as db:
            meeting = await db.get(Meeting, mid)
            if not meeting:
                target.unlink(missing_ok=True)
                return
            meeting.duration_seconds = max(meeting.duration_seconds or 0, target.stat().st_size // 32000)
            meeting.processing_state = {"stage": "queued", "progress": 10}
            await db.commit()

        await live_bus.publish(meeting_id, {"type": "processing", "stage": "transcribing", "progress": 10})
        await run_finalize_pipeline(meeting_id)
    except Exception as exc:
        log.exception("import fallo meeting=%s", meeting_id)
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, mid)
            if meeting:
                meeting.status = "failed"
                meeting.processing_state = {"stage": "failed", "error": str(exc)[:400]}
                await db.commit()
        await live_bus.publish(meeting_id, {"type": "status", "status": "failed"})
    finally:
        # PRIVACY: el original se borra pase lo que pase; el audio de trabajo
        # lo cierra la pasada final (se borra, o va al Drive si se grababa).
        _remove(source_path)
