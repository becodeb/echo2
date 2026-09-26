"""Quién ve qué reunión: la regla, en un solo lugar.

Una reunión es visible para una persona si se cumple cualquiera de estas:
- es admin u owner de la organización (o superadmin de la instalación);
- la creó;
- se la compartieron (MeetingShare);
- no es privada y la persona tiene acceso "total" o "direccion" a su nivel.

Las reuniones internas (kind="interna": directivos, coordinadores...) tienen
otra regla: las ve quien la creó, a quien se la compartieron y quien es del
grupo de la reunión. Ser admin u owner NO alcanza, y el nivel no cuenta: una
reunión de directivos no la ve la secretaria que administra la sede salvo que
la sumen al grupo (y eso queda en auditoría).

"limitado" en un nivel no suma nada a lo de arriba: deja crear reuniones en
ese nivel, pero solo se ve lo propio y lo compartido. Sin fila es "nulo".

Todo lo que muestra contenido de reuniones pasa por acá: el detalle (vía
deps.check_meeting_access) y también los listados que cruzan reuniones
(búsqueda, chat global, tareas, reportes, inicio, personas, proyectos,
memoria). Por eso hay dos versiones de la misma regla: `meeting_filter`
para meter en una consulta y `can_see` para una reunión ya cargada. Si se
cambia una, se cambia la otra; los tests de test_levels.py cubren las dos.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..models import (
    LEVELS,
    InternalGroupMember,
    Meeting,
    MeetingShare,
    MemberLevelAccess,
    OrganizationMember,
)

FULL_ACCESS = ("direccion", "total")


@dataclass(frozen=True)
class Scope:
    user_id: uuid.UUID
    org_id: uuid.UUID
    # Admin u owner de la sede, o superadmin: ve todo sin mirar niveles.
    sees_everything: bool
    # Nivel -> acceso, solo las filas que tiene.
    access: dict[str, str]
    # Grupos internos de los que es miembro: deciden las reuniones internas.
    groups: frozenset[uuid.UUID] = frozenset()

    @property
    def full_levels(self) -> set[str]:
        return {level for level, access in self.access.items() if access in FULL_ACCESS}

    @property
    def managed_levels(self) -> set[str]:
        if self.sees_everything:
            return set(LEVELS)
        return {level for level, access in self.access.items() if access == "direccion"}

    @property
    def creatable_levels(self) -> list[str]:
        """Niveles en los que puede crear reuniones, en el orden de LEVELS."""
        return [level for level in LEVELS if self.sees_everything or level in self.access]

    @property
    def needs_level(self) -> bool:
        """Entró a la sede pero todavía no dijo de qué nivel es."""
        return not self.sees_everything and not self.access


async def load_scope(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: str) -> Scope:
    rows = (
        await db.execute(
            select(MemberLevelAccess.level, MemberLevelAccess.access).where(
                MemberLevelAccess.organization_id == org_id, MemberLevelAccess.user_id == user_id
            )
        )
    ).all()
    groups = (
        await db.execute(
            select(InternalGroupMember.group_id).where(
                InternalGroupMember.organization_id == org_id, InternalGroupMember.user_id == user_id
            )
        )
    ).scalars().all()
    return Scope(
        user_id=user_id,
        org_id=org_id,
        sees_everything=role in ("admin", "owner"),
        access={level: access for level, access in rows},
        groups=frozenset(groups),
    )


def _not_private() -> ColumnElement[bool]:
    return func.coalesce(Meeting.meta["visibility"].astext, "org") != "private"


def meeting_filter(scope: Scope) -> ColumnElement[bool]:
    """Condición sobre `Meeting` para usar en un WHERE. No filtra por org ni borradas."""
    shared = exists().where(MeetingShare.meeting_id == Meeting.id, MeetingShare.user_id == scope.user_id)
    own_or_shared = or_(Meeting.created_by == scope.user_id, shared)
    by_group = Meeting.group_id.in_(scope.groups) if scope.groups else false()
    internal = and_(Meeting.kind == "interna", or_(own_or_shared, by_group))
    if scope.sees_everything:
        return or_(Meeting.kind != "interna", internal)
    full_levels = scope.full_levels
    by_level = and_(Meeting.level.in_(full_levels), _not_private()) if full_levels else false()
    return or_(and_(Meeting.kind != "interna", or_(own_or_shared, by_level)), internal)


def visible_meeting_ids(scope: Scope):
    """Subconsulta con los ids de reuniones visibles de la organización."""
    return select(Meeting.id).where(
        Meeting.organization_id == scope.org_id,
        Meeting.deleted_at.is_(None),
        meeting_filter(scope),
    )


def meeting_id_filter(scope: Scope, column) -> ColumnElement[bool]:
    """Para tablas que cuelgan de una reunión (decisiones, tareas, segmentos...).

    Sin atajo para admins: las reuniones internas de un grupo al que no
    pertenecen tampoco las ven, así que siempre hay que filtrar.
    """
    return column.in_(visible_meeting_ids(scope))


async def visible_meeting_id_list(db: AsyncSession, scope: Scope) -> list[uuid.UUID] | None:
    """Los ids como lista, para SQL crudo. None = todas (no hace falta filtrar)."""
    return list((await db.execute(visible_meeting_ids(scope))).scalars().all())


async def users_who_can_see(db: AsyncSession, meeting: Meeting) -> list[uuid.UUID]:
    """Miembros de la sede que ven esta reunión: a quién mandarle avisos sobre ella."""
    private = (meeting.meta or {}).get("visibility", "org") == "private"
    conditions = [
        OrganizationMember.user_id == meeting.created_by,
        OrganizationMember.user_id.in_(
            select(MeetingShare.user_id).where(MeetingShare.meeting_id == meeting.id)
        ),
    ]
    if meeting.kind == "interna":
        if meeting.group_id:
            conditions.append(
                OrganizationMember.user_id.in_(
                    select(InternalGroupMember.user_id).where(InternalGroupMember.group_id == meeting.group_id)
                )
            )
    else:
        conditions.append(OrganizationMember.role.in_(("admin", "owner")))
    if meeting.kind != "interna" and not private and meeting.level:
        conditions.append(
            OrganizationMember.user_id.in_(
                select(MemberLevelAccess.user_id).where(
                    MemberLevelAccess.organization_id == meeting.organization_id,
                    MemberLevelAccess.level == meeting.level,
                    MemberLevelAccess.access.in_(FULL_ACCESS),
                )
            )
        )
    return list(
        (
            await db.execute(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.organization_id == meeting.organization_id, or_(*conditions)
                )
            )
        )
        .scalars()
        .all()
    )


def can_see_by_rule(scope: Scope, meeting: Meeting) -> bool:
    """La regla sin el compartido (que necesita la base). Espejo de meeting_filter."""
    if meeting.created_by == scope.user_id:
        return True
    if meeting.kind == "interna":
        return meeting.group_id is not None and meeting.group_id in scope.groups
    if scope.sees_everything:
        return True
    private = (meeting.meta or {}).get("visibility", "org") == "private"
    return not private and meeting.level in scope.full_levels
