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
from .services.access import Scope, can_see_by_rule, load_scope

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
    def __init__(
        self, org: Organization, member: OrganizationMember, user: User, superadmin_visit: bool = False
    ):
        self.org = org
        self.member = member
        self.user = user
        # Superadmin de la instalación mirando una sede de la que no es
        # miembro: actúa como owner, pero no figura entre los miembros.
        self.superadmin_visit = superadmin_visit
        self._scope: Scope | None = None

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id

    @property
    def role(self) -> str:
        return self.member.role

    def require_role(self, minimum: str) -> None:
        if ROLE_ORDER.get(self.role, -1) < ROLE_ORDER.get(minimum, 99):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")

    async def scope(self, db: AsyncSession) -> Scope:
        """Qué reuniones ve en esta sede (services/access.py). Se calcula una vez por pedido."""
        if self._scope is None:
            self._scope = await load_scope(db, self.org_id, self.user.id, self.role)
        return self._scope


# Última vez que se registró la visita de un superadmin a cada sede: se anota
# una por hora y no una por pedido, que llenaría el log de ruido.
_superadmin_visits: dict[tuple[uuid.UUID, uuid.UUID], float] = {}


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
    if row:
        member, org = row
        return OrgContext(org=org, member=member, user=user)

    # Los superadmins de la instalación ven todas las sedes. No se los suma
    # como miembros (no aparecen en la lista de la sede) y queda registrado en
    # el log de auditoría de esa sede que entraron.
    if user.is_superadmin:
        org = await db.get(Organization, org_id)
        if org is not None and org.deleted_at is None:
            key = (user.id, org.id)
            now = time.monotonic()
            if now - _superadmin_visits.get(key, -3600.0) >= 3600:
                _superadmin_visits[key] = now
                from .services.audit import audit

                await audit(db, org.id, user.id, "admin.superadmin_visit", "organization", str(org.id),
                            detail={"by": user.email})
                await db.commit()
            member = OrganizationMember(organization_id=org.id, user_id=user.id, role=ROLE_OWNER)
            return OrgContext(org=org, member=member, user=user, superadmin_visit=True)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "No pertenecés a esta organización")


# Desenlaces de la regla de visibilidad. Son tres y no dos porque "para vos
# esta reunión no existe" y "existe pero no con ese permiso" son respuestas
# distintas: la primera se responde como inexistente justamente para no filtrar
# que existe, y colapsarlas en un booleano perdería esa diferencia.
MEETING_ACCESS_OK = "ok"
MEETING_ACCESS_HIDDEN = "hidden"
MEETING_ACCESS_INSUFFICIENT_ROLE = "insufficient_role"


async def check_meeting_access(
    db: AsyncSession,
    meeting: Meeting,
    user: User,
    role: str,
    minimum_role: str = "viewer",
) -> str:
    """Regla de visibilidad de una reunión, en un solo lugar.

    Vive suelta y no adentro de `get_meeting_or_404` porque el WebSocket en
    vivo (`routers/live.py`) necesita exactamente esta decisión y no tiene un
    `OrgContext` que pasarle: recibe el rol del `OrganizationMember` que ya
    consultó. Mientras la regla estuvo escrita dos veces, una de las dos copia
    se quedó atrás y un `member` que comía 404 por REST igual abría el WS y se
    llevaba el transcript privado completo.

    Asume que la reunión ya fue cargada y que la pertenencia a la organización
    ya fue verificada: acá sólo se decide visibilidad. Quien llama traduce el
    resultado al vocabulario de su transporte (404 en HTTP, 4403 en WebSocket).

    La regla en sí (admin, creador, nivel) vive en services/access.py, que es
    la misma que filtran los listados. Lo que agrega esta función es el
    compartido con su rol mínimo: por nivel o por ser creador se ve sin mirar
    `minimum_role`, porque un compartido no puede darle menos permiso del que
    ya tenía.
    """
    scope = await load_scope(db, meeting.organization_id, user.id, role)
    if can_see_by_rule(scope, meeting):
        return MEETING_ACCESS_OK

    share = (
        await db.execute(
            select(MeetingShare).where(
                MeetingShare.meeting_id == meeting.id,
                MeetingShare.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not share:
        return MEETING_ACCESS_HIDDEN
    if ROLE_ORDER.get(share.role, 0) < ROLE_ORDER.get(minimum_role, 0):
        return MEETING_ACCESS_INSUFFICIENT_ROLE
    return MEETING_ACCESS_OK


async def user_can_access_meeting(
    db: AsyncSession,
    meeting: Meeting,
    user: User,
    role: str,
    minimum_role: str = "viewer",
) -> bool:
    """Versión booleana para quien no distingue "oculta" de "sin permiso".

    El WebSocket es ese caso: cierra con 4403 en cualquiera de los dos
    desenlaces negativos, porque su protocolo no tiene forma de decir otra cosa.
    """
    return (
        await check_meeting_access(db, meeting, user, role, minimum_role)
        == MEETING_ACCESS_OK
    )


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

    access = await check_meeting_access(db, meeting, ctx.user, ctx.role, minimum_role)
    if access == MEETING_ACCESS_HIDDEN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión no encontrada")
    if access == MEETING_ACCESS_INSUFFICIENT_ROLE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")
    return meeting


def can_edit_meeting(ctx: OrgContext, meeting: Meeting) -> bool:
    if meeting.created_by == ctx.user.id:
        return True
    return ROLE_ORDER.get(ctx.role, -1) >= ROLE_ORDER["member"]


# ── Rate limiting simple en memoria (por proceso) ────────────────
_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    from .config import get_settings

    if get_settings().echo_env == "test":
        return  # la suite crea muchos usuarios; el limite se prueba aparte
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas solicitudes, esperá un momento")
    bucket.append(now)
