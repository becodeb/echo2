"""Recordatorio de "Mi voz" en la campanita para quien no la grabó.

Pedido de Bauti (27/10): que grabarla sea "medio obligatorio". A cada persona
sin muestra (o con una de antes del mínimo de 8 s, que Echo no usa) le llega
una notificación por organización. Nunca se apilan: hay una sola por persona
y sede; si la leyó y pasaron REMIND_EVERY días sin grabar, la misma vuelve a
quedar sin leer y arriba de la lista. Al grabar la voz se borran
(routers/my_voice.py).
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from ..db import SessionLocal
from ..models import Notification, Organization, OrganizationMember, User, UserVoiceSample
from . import voiceprint

log = logging.getLogger("echo.voice_reminder")

VOICE_REMINDER_KIND = "voice_missing"
REMIND_EVERY = timedelta(days=3)
CHECK_EVERY_SECONDS = 60 * 60
TITLE = "Grabá tu voz: son 12 segundos"
BODY = "Así Echo sabe cuándo hablás vos y en tus reuniones aparecés con tu nombre, no como «Persona 1»."
LINK = "/settings/my-voice"


async def remind_missing_voices(now: datetime | None = None) -> int:
    """Crea o reactiva los recordatorios. Devuelve cuántos quedaron sin leer."""
    now = now or datetime.now(UTC)
    async with SessionLocal() as db:
        members = (
            await db.execute(
                select(OrganizationMember.user_id, OrganizationMember.organization_id)
                .join(User, User.id == OrganizationMember.user_id)
                .join(Organization, Organization.id == OrganizationMember.organization_id)
                .outerjoin(UserVoiceSample, UserVoiceSample.user_id == OrganizationMember.user_id)
                .where(
                    User.is_active.is_(True),
                    Organization.deleted_at.is_(None),
                    or_(UserVoiceSample.id.is_(None), UserVoiceSample.duration_ms < voiceprint.MIN_SAMPLE_MS),
                )
            )
        ).all()
        if not members:
            return 0
        existing = {
            (row.user_id, row.organization_id): row
            for row in (
                await db.execute(
                    select(Notification).where(
                        Notification.kind == VOICE_REMINDER_KIND,
                        Notification.user_id.in_({user_id for user_id, _ in members}),
                    )
                )
            ).scalars()
        }
        changed = 0
        for user_id, org_id in members:
            row = existing.get((user_id, org_id))
            if row is None:
                db.add(Notification(user_id=user_id, organization_id=org_id, kind=VOICE_REMINDER_KIND,
                                    title=TITLE, body=BODY, link=LINK))
                changed += 1
            elif row.read_at is not None and row.read_at < now - REMIND_EVERY:
                row.read_at = None
                row.created_at = now
                changed += 1
        await db.commit()
    if changed:
        log.info("recordatorios de Mi voz: %d", changed)
    return changed


async def reminder_loop() -> None:
    while True:
        try:
            await remind_missing_voices()
        except Exception:  # noqa: BLE001 - el loop nunca se cae
            log.exception("recordatorios de Mi voz fallidos")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
