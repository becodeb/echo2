"""Dependencias FastAPI: usuario actual, organización activa, RBAC, rate limiting.

Regla de oro (tenant isolation): NUNCA confiar en un organization_id que venga
del frontend sin verificar la membresía del usuario. Toda query pasa por acá.
"""
import time
import uuid
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    Meeting,
    MeetingShare,
    Organization,
    OrganizationMember,
    User,
)
from .security import decode_token

ROLE_ORDER = {"viewer": 0, "commenter": 0, "member": 1, "editor": 1, "admin": 2, "owner": 3}


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inválido")
    return user


class OrgContext:
    def __init__(self, org: Organization, member: OrganizationMember, user: User):
        self.org = org
        self.member = member
        self.user = user

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id

    @property
    def role(self) -> str:
        return self.member.role

    def require_role(self, minimum: str) -> None:
        if ROLE_ORDER.get(self.role, -1) < ROLE_ORDER.get(minimum, 99):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")


async def get_org_context(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_organization_id: str | None = Header(default=None),
) -> OrgContext:
    """Resuelve la organización activa VERIFICANDO la membresía en DB."""
    if not x_organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta el header X-Organization-Id")
    try:
        org_id = uuid.UUID(x_organization_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Organization-Id inválido")

    result = await db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
            Organization.deleted_at.is_(None),
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No pertenecés a esta organización")
    member, org = row
    return OrgContext(org=org, member=member, user=user)


async def get_meeting_or_404(
    meeting_id: uuid.UUID,
    ctx: OrgContext,
    db: AsyncSession,
    minimum_role: str = "viewer",
) -> Meeting:
    """Carga una reunión SIEMPRE filtrando por la organización del contexto."""
    meeting = (
        await db.execute(
            select(Meeting).where(
                Meeting.id == meeting_id,
                Meeting.organization_id == ctx.org_id,
                Meeting.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not meeting:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión no encontrada")

    visibility = (meeting.meta or {}).get("visibility", "org")
    if visibility == "private" and ROLE_ORDER.get(ctx.role, -1) < ROLE_ORDER["admin"]:
        if meeting.created_by != ctx.user.id:
            share = (
                await db.execute(
                    select(MeetingShare).where(
                        MeetingShare.meeting_id == meeting.id,
                        MeetingShare.user_id == ctx.user.id,
                    )
                )
            ).scalar_one_or_none()
            if not share:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión no encontrada")
            if ROLE_ORDER.get(share.role, 0) < ROLE_ORDER.get(minimum_role, 0):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")
    return meeting


def can_edit_meeting(ctx: OrgContext, meeting: Meeting) -> bool:
    if meeting.created_by == ctx.user.id:
        return True
    return ROLE_ORDER.get(ctx.role, -1) >= ROLE_ORDER["member"]


# ── Rate limiting simple en memoria (por proceso) ────────────────
_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas solicitudes, esperá un momento")
    bucket.append(now)
