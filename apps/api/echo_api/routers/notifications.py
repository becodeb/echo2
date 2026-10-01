"""Notificaciones in-app."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Avisos de la plataforma a toda la gente (ej. una mejora). La web los muestra
# emergentes una sola vez; se cargan con una migración.
ANNOUNCEMENT_PREFIX = "announcement:"


@router.get("")
async def list_notifications(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
):
    # Los pedidos de plan le llegan al superadmin desde la organización de
    # quien pide: los ve en cualquier sede en la que esté.
    scope = Notification.organization_id == ctx.org_id
    if ctx.user.is_superadmin:
        scope = or_(scope, Notification.kind == "plan_request")
    query = (
        select(Notification)
        .where(Notification.user_id == ctx.user.id, scope)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = (await db.execute(query)).scalars().all()
    unread = sum(1 for n in rows if n.read_at is None)
    return {
        "unread_count": unread,
        "notifications": [
            {
                "id": str(n.id),
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "read": n.read_at is not None,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


@router.post("/read-all", status_code=204)
async def mark_all_read(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == ctx.user.id,
            or_(Notification.organization_id == ctx.org_id, Notification.kind == "plan_request")
            if ctx.user.is_superadmin
            else Notification.organization_id == ctx.org_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != ctx.user.id:
        return
    condition = Notification.id == notification.id
    # Un anuncio se ve una vez por persona, no una por sede: cerrarlo en una
    # lo cierra en todas.
    if notification.kind.startswith(ANNOUNCEMENT_PREFIX):
        condition = Notification.kind == notification.kind
    await db.execute(
        update(Notification)
        .where(condition, Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
