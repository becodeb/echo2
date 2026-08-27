"""Notificaciones in-app."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
):
    query = (
        select(Notification)
        .where(
            Notification.user_id == ctx.user.id,
            Notification.organization_id == ctx.org_id,
        )
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
            Notification.organization_id == ctx.org_id,
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
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == ctx.user.id)
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
