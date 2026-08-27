"""Audit log helper."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog


async def audit(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=org_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=ip,
        )
    )
