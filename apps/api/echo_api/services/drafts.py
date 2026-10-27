"""Borradores abandonados: reuniones que se crearon y nunca arrancaron.

Se crean al tocar "Nueva reunión" y quedan en "Borrador" si nadie graba (se
cerró la pestaña, se probó el micrófono). Pasadas 24 horas sin audio ni
transcripción se borran solas. Es baja lógica (deleted_at), como el botón de
borrar, y queda en auditoría: se pueden recuperar desde la base.
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select

from ..db import SessionLocal
from ..models import Meeting, TranscriptSegment
from .audit import audit
from .recording import pcm_path

log = logging.getLogger("echo.drafts")

DRAFT_MAX_AGE = timedelta(hours=24)
CLEANUP_EVERY_SECONDS = 60 * 60


async def cleanup_drafts(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with SessionLocal() as db:
        drafts = (
            await db.execute(
                select(Meeting).where(
                    Meeting.status == "draft",
                    Meeting.deleted_at.is_(None),
                    Meeting.created_at < now - DRAFT_MAX_AGE,
                    ~exists().where(TranscriptSegment.meeting_id == Meeting.id),
                )
            )
        ).scalars().all()
        removed = 0
        for meeting in drafts:
            if pcm_path(meeting.id).exists():
                continue  # tiene audio guardado: no es un borrador vacío
            meeting.deleted_at = now
            await audit(db, meeting.organization_id, None, "meeting.draft_cleanup", "meeting", str(meeting.id),
                        detail={"title": meeting.title, "created_by": str(meeting.created_by)})
            removed += 1
        await db.commit()
    if removed:
        log.info("borradores abandonados borrados: %d", removed)
    return removed


async def cleanup_loop() -> None:
    while True:
        try:
            await cleanup_drafts()
        except Exception:  # noqa: BLE001 - el loop nunca se cae
            log.exception("limpieza de borradores fallida")
        await asyncio.sleep(CLEANUP_EVERY_SECONDS)
