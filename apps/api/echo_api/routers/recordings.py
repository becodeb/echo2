"""Grabación del audio completo de una reunión (services/recording.py).

La pantalla puede activarla o desactivarla antes de finalizar, descargar el
mp3 mientras está de paso en el servidor, mandarlo al Drive de quien mira o
descartarlo ya. Cualquier acción respeta la visibilidad de la reunión.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..services import recording as rec
from ..services.audit import audit
from ..services.drive import get_user_connection
from .meetings import public_recording

router = APIRouter(prefix="/api/meetings", tags=["recordings"])


class RecordingToggleIn(BaseModel):
    enabled: bool


@router.put("/{meeting_id}/recording")
async def set_recording(
    meeting_id: uuid.UUID,
    data: RecordingToggleIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    if meeting.status not in ("draft", "live", "paused"):
        raise HTTPException(status.HTTP_409_CONFLICT, "La reunión ya terminó")
    if data.enabled:
        current = meeting.recording or {}
        meeting.recording = {
            **current,
            "enabled": True,
            "status": current.get("status") if current.get("enabled") else "pending",
            "user_id": current.get("user_id") or str(ctx.user.id),
        }
    else:
        # Apagarla a mitad de reunión descarta lo grabado hasta ahí: es lo que
        # se espera de "no grabar".
        rec.pcm_path(meeting.id).unlink(missing_ok=True)
        meeting.recording = {**(meeting.recording or {}), "enabled": False, "status": "discarded"}
    await audit(db, ctx.org_id, ctx.user.id, "meeting.recording", "meeting", str(meeting.id),
                detail={"enabled": data.enabled})
    await db.commit()
    return public_recording(meeting.recording)


@router.get("/{meeting_id}/recording/file")
async def download_recording(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    path = rec.mp3_path(meeting.id)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El audio ya no está en el servidor")
    fecha = (meeting.started_at or meeting.created_at).strftime("%Y-%m-%d")
    safe_title = "".join(char for char in meeting.title[:60] if char.isalnum() or char in " -_").strip() or "reunion"
    await audit(db, ctx.org_id, ctx.user.id, "meeting.recording_download", "meeting", str(meeting.id))
    await db.commit()
    return FileResponse(path, media_type=rec.MP3_MIME, filename=f"{fecha} {safe_title}.mp3")


@router.post("/{meeting_id}/recording/drive")
async def send_recording_to_drive(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manda el audio que quedó para descargar al Drive de quien lo pide."""
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not rec.mp3_path(meeting.id).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El audio ya no está en el servidor")
    if await get_user_connection(db, ctx.user.id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Conectá tu Google Drive en Ajustes → Mi Google Drive")
    state = await rec.upload_to_drive(meeting.id, ctx.user.id)
    await audit(db, ctx.org_id, ctx.user.id, "meeting.recording_drive", "meeting", str(meeting.id))
    await db.commit()
    if not state or state.get("status") != "uploaded":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, (state or {}).get("error") or "No se pudo subir a Drive")
    return public_recording(state)


@router.delete("/{meeting_id}/recording/file")
async def discard_recording(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso")
    await audit(db, ctx.org_id, ctx.user.id, "meeting.recording_discard", "meeting", str(meeting.id))
    await db.commit()
    return public_recording(await rec.discard_file(meeting.id))
