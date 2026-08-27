"""Importar una reunión ya grabada (MP3/WAV/M4A/WebM/MP4).

Privacy-first: el archivo se procesa en memoria/archivo temporal y se elimina
inmediatamente después de transcribir. Nunca se archiva el audio.
"""
import asyncio
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context
from ..models import Meeting, TranscriptSegment
from ..services.ai_settings import get_vocabulary, resolve_stt
from ..services.audit import audit
from ..services.live_bus import live_bus
from ..services.pipeline import run_finalize_pipeline
from ..services.stt import get_stt_provider

log = logging.getLogger("echo.imports")

router = APIRouter(prefix="/api/meetings", tags=["imports"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".flac"}


@router.post("/{meeting_id}/import", status_code=202)
async def import_recording(
    meeting_id: uuid.UUID,
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

    stt_config = await resolve_stt(db, ctx.org_id)
    if stt_config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No hay motor de transcripción configurado (Ajustes → Speech-to-Text)",
        )

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Archivo demasiado grande")

    meeting.status = "processing"
    meeting.audio_source = "import"
    meeting.processing_state = {"stage": "transcribing", "progress": 5}
    await audit(db, ctx.org_id, ctx.user.id, "meeting.import", "meeting", str(meeting.id),
                detail={"filename": file.filename, "bytes": len(data)})
    await db.commit()

    vocabulary = await get_vocabulary(db, ctx.org_id)
    asyncio.create_task(
        _process_import(
            str(meeting.id), data, file.filename or f"audio{extension}", meeting.language,
            stt_config.provider, stt_config.api_key, stt_config.model, vocabulary,
        )
    )
    return {"status": "processing"}


async def _process_import(
    meeting_id: str,
    data: bytes,
    filename: str,
    language: str,
    provider_name: str,
    api_key: str,
    model: str | None,
    vocabulary: list[str],
) -> None:
    mid = uuid.UUID(meeting_id)
    provider = get_stt_provider(provider_name, api_key, model)
    temp_path = None
    try:
        # transcodificar a WAV 16k mono con ffmpeg si no es wav (archivo temporal
        # de vida mínima; se borra en el finally pase lo que pase)
        payload = data
        send_name = filename
        if not filename.lower().endswith(".wav"):
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as source:
                source.write(data)
                temp_path = source.name
            wav_path = temp_path + ".wav"
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", temp_path, "-ac", "1", "-ar", "16000", wav_path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            if process.returncode == 0 and os.path.exists(wav_path):
                with open(wav_path, "rb") as converted:
                    payload = converted.read()
                send_name = "audio.wav"
                os.unlink(wav_path)
            # si ffmpeg falla se manda el original: los providers aceptan varios formatos
        del data  # liberar el buffer original cuanto antes

        result = await provider.transcribe_file(payload, send_name, language, vocabulary)
        del payload

        async with SessionLocal() as db:
            meeting = await db.get(Meeting, mid)
            if not meeting:
                return
            seq = 0
            for segment in result.segments:
                text = segment.text.strip()
                if not text:
                    continue
                seq += 1
                db.add(
                    TranscriptSegment(
                        meeting_id=mid,
                        organization_id=meeting.organization_id,
                        seq=seq,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        text=text,
                        confidence=segment.confidence,
                        is_final=True,
                    )
                )
            if result.segments:
                meeting.duration_seconds = max(
                    meeting.duration_seconds, int(result.segments[-1].end_ms / 1000)
                )
            meeting.processing_state = {"stage": "queued", "progress": 20}
            await db.commit()

        await live_bus.publish(meeting_id, {"type": "processing", "stage": "transcribed", "progress": 20})
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
        # PRIVACY: eliminar cualquier archivo temporal pase lo que pase
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
