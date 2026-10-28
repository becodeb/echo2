"""Quién ve qué reunión: la regla, en un solo lugar.

Una reunión es visible para una persona si se cumple cualquiera de estas:
- es admin u owner de la organización (o superadmin de la instalación);
- la creó;
- estuvo en ella: la marcaron entre "quiénes del colegio estuvieron"
  (MeetingParticipant con su usuario) o Echo la reconoció por la voz
  (Speaker con su usuario);
- se la compartieron (MeetingShare);
- no es privada y la persona está asignada a la familia de la reunión
  (FamilyAssignment: la tutora, el DOE que sigue a esa familia);
- no es privada y la persona tiene acceso "total" a su nivel;
- no es privada, la persona es "adviser" del nivel y la creó alguien con
  acceso "limitado" o "tutor" en ese nivel (la adviser es la jefa de las
  coordinadoras del DOE: ve lo que hace el DOE, no lo de los directivos).

Las reuniones internas (kind="interna": directivos, coordinadores...) tienen
otra regla: las ve quien la creó, quien estuvo, a quien se la compartieron y
quien es del grupo de la reunión. Ser admin u owner NO alcanza, y el nivel no cuenta: una
reunión de directivos no la ve la secretaria que administra la sede salvo que
la sumen al grupo (y eso queda en auditoría).

"limitado" (el DOE), "tutor" (igual que el DOE) y "direccion" (directivo) no
suman nada a lo de arriba: dejan crear reuniones en ese nivel, pero solo se
ve lo propio, donde estuvo, lo compartido y lo de sus familias. Un directivo
no ve las reuniones de otro directivo. Sin fila es "nulo".

Todo lo que muestra contenido de reuniones pasa por acá: el detalle (vía
deps.check_meeting_access) y también los listados que cruzan reuniones
(búsqueda, chat global, tareas, reportes, inicio, personas, proyectos,
memoria). Por eso hay dos versiones de la misma regla: `meeting_filter`
para meter en una consulta y `can_see` para una reunión ya cargada. Si se
cambia una, se cambia la otra; los tests de test_levels.py cubren las dos.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import String, and_, cast, exists, false, func, literal, null, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from ..models import (
    LEVELS,
    FamilyAssignment,
    InternalGroupMember,
    Meeting,
    MeetingParticipant,
    MeetingShare,
    MemberLevelAccess,
    OrganizationMember,
    Speaker,
)

# Acceso por nivel (member_level_access.access, un string: sumar uno no pide migración).
FULL_ACCESS = ("total",)  # ve todo el nivel
ADVISER_ACCESS = "adviser"  # lo suyo + lo que crea el DOE del nivel
DOE_ACCESS = ("limitado", "tutor")  # el DOE y las tutoras: solo lo suyo
# Lo que un directivo puede dar o sacar: nada que muestre más de lo que ve él.
DIRECTIVO_CAN_ASSIGN = ("limitado", "tutor", "nulo")


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
    # Familias a las que está asignada: ve todas sus reuniones no privadas.
    families: frozenset[uuid.UUID] = frozenset()

    @property
    def full_levels(self) -> set[str]:
        return {level for level, access in self.access.items() if access in FULL_ACCESS}

    @property
    def adviser_levels(self) -> set[str]:
        return {level for level, access in self.access.items() if access == ADVISER_ACCESS}

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
    # Niveles y grupos en una sola ida a la base: casi todos los pedidos pasan
    # por acá y con el servidor cargado cada ida y vuelta se nota.
    levels = select(
        literal("nivel").label("tipo"), MemberLevelAccess.level.label("clave"), MemberLevelAccess.access.label("valor")
    ).where(MemberLevelAccess.organization_id == org_id, MemberLevelAccess.user_id == user_id)
    groups = select(
        literal("grupo").label("tipo"), cast(InternalGroupMember.group_id, String).label("clave"),
        cast(null(), String).label("valor"),
    ).where(InternalGroupMember.organization_id == org_id, InternalGroupMember.user_id == user_id)
    families = select(
        literal("familia").label("tipo"), cast(FamilyAssignment.family_id, String).label("clave"),
        cast(null(), String).label("valor"),
    ).where(FamilyAssignment.organization_id == org_id, FamilyAssignment.user_id == user_id)
    rows = (await db.execute(union_all(levels, groups, families))).all()
    return Scope(
        user_id=user_id,
        org_id=org_id,
        sees_everything=role in ("admin", "owner"),
        access={key: value for kind, key, value in rows if kind == "nivel"},
        groups=frozenset(uuid.UUID(key) for kind, key, _ in rows if kind == "grupo"),
        families=frozenset(uuid.UUID(key) for kind, key, _ in rows if kind == "familia"),
    )


def _not_private() -> ColumnElement[bool]:
    return func.coalesce(Meeting.meta["visibility"].astext, "org") != "private"


def _present(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Estuvo en la reunión: la marcaron como presente o Echo la reconoció por la voz.

    Con alias: hay listados que ya hacen join con los participantes y, sin
    ellos, la subconsulta se correlaciona con esa tabla y queda sin FROM.
    """
    participant = aliased(MeetingParticipant)
    speaker = aliased(Speaker)
    return or_(
        exists().where(participant.meeting_id == Meeting.id, participant.user_id == user_id),
        exists().where(speaker.meeting_id == Meeting.id, speaker.user_id == user_id),
    )


def _created_by_doe() -> ColumnElement[bool]:
    """Quien creó la reunión tiene acceso "limitado" o "tutor" al nivel de la reunión."""
    creator = aliased(MemberLevelAccess)
    return exists().where(
        creator.organization_id == Meeting.organization_id,
        creator.user_id == Meeting.created_by,
        creator.level == Meeting.level,
        creator.access.in_(DOE_ACCESS),
    )


def meeting_filter(scope: Scope) -> ColumnElement[bool]:
    """Condición sobre `Meeting` para usar en un WHERE. No filtra por org ni borradas."""
    shared = exists().where(MeetingShare.meeting_id == Meeting.id, MeetingShare.user_id == scope.user_id)
    own_or_shared = or_(Meeting.created_by == scope.user_id, shared, _present(scope.user_id))
    by_group = Meeting.group_id.in_(scope.groups) if scope.groups else false()
    internal = and_(Meeting.kind == "interna", or_(own_or_shared, by_group))
    if scope.sees_everything:
        return or_(Meeting.kind != "interna", internal)
    full_levels = scope.full_levels
    by_level = and_(Meeting.level.in_(full_levels), _not_private()) if full_levels else false()
    adviser_levels = scope.adviser_levels
    by_adviser = (
        and_(Meeting.level.in_(adviser_levels), _not_private(), _created_by_doe()) if adviser_levels else false()
    )
    by_family = and_(Meeting.family_id.in_(scope.families), _not_private()) if scope.families else false()
    return or_(and_(Meeting.kind != "interna", or_(own_or_shared, by_level, by_adviser, by_family)), internal)


async def is_present(db: AsyncSession, meeting_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """La presencia para una reunión ya cargada (can_see_by_rule no mira la base)."""
    participant = (
        select(MeetingParticipant.id)
        .where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user_id)
        .correlate(None)
        .exists()
    )
    speaker = (
        select(Speaker.id).where(Speaker.meeting_id == meeting_id, Speaker.user_id == user_id).correlate(None).exists()
    )
    return bool((await db.execute(select(or_(participant, speaker)))).scalar())


async def creator_is_doe(db: AsyncSession, meeting: Meeting) -> bool:
    """Espejo de _created_by_doe para una reunión ya cargada."""
    if meeting.level is None:
        return False
    found = exists().where(
        MemberLevelAccess.organization_id == meeting.organization_id,
        MemberLevelAccess.user_id == meeting.created_by,
        MemberLevelAccess.level == meeting.level,
        MemberLevelAccess.access.in_(DOE_ACCESS),
    )
    return bool((await db.execute(select(found))).scalar())


async def can_see(db: AsyncSession, scope: Scope, meeting: Meeting) -> bool:
    """Misma regla que meeting_filter para una reunión ya cargada (el compartido lo mira quien llama)."""
    if can_see_by_rule(scope, meeting) or await is_present(db, meeting.id, scope.user_id):
        return True
    if meeting.kind == "interna" or meeting.level not in scope.adviser_levels:
        return False
    if (meeting.meta or {}).get("visibility", "org") == "private":
        return False
    return await creator_is_doe(db, meeting)


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


# Rango dentro de la sede, para repartir tareas: a alguien de igual o menor
# rango, nunca para arriba (un DOE no le asigna tareas a la directora).
RANK_ADMIN = 4  # owner o admin de la sede
RANK_TOTAL = 3  # "total" en algún nivel: ve todo, es dirección del nivel
RANK_DIRECTIVO = 2  # "adviser" o "direccion" en algún nivel
RANK_EQUIPO = 1  # "limitado"/"tutor" (DOE, docentes) o sin nivel
RANK_LABEL = {
    RANK_ADMIN: "Dirección de la sede",
    RANK_TOTAL: "Ve todo",
    RANK_DIRECTIVO: "Directivo",
    RANK_EQUIPO: "Equipo",
}
ADVISER_LABEL = "Adviser"


def rank_of(role: str, accesses) -> int:
    accesses = list(accesses)
    if role in ("admin", "owner"):
        return RANK_ADMIN
    if any(access in FULL_ACCESS for access in accesses):
        return RANK_TOTAL
    if any(access in (ADVISER_ACCESS, "direccion") for access in accesses):
        return RANK_DIRECTIVO
    return RANK_EQUIPO


def label_of(role: str, accesses) -> str:
    accesses = list(accesses)
    rank = rank_of(role, accesses)
    if rank == RANK_DIRECTIVO and "direccion" not in accesses:
        return ADVISER_LABEL
    return RANK_LABEL[rank]


async def member_ranks_and_labels(
    db: AsyncSession, org_id: uuid.UUID
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, str]]:
    """Rango y nombre del rango de cada persona de la sede."""
    roles = dict(
        (
            await db.execute(
                select(OrganizationMember.user_id, OrganizationMember.role).where(
                    OrganizationMember.organization_id == org_id
                )
            )
        ).all()
    )
    accesses: dict[uuid.UUID, list[str]] = {}
    for user_id, access in (
        await db.execute(
            select(MemberLevelAccess.user_id, MemberLevelAccess.access).where(
                MemberLevelAccess.organization_id == org_id
            )
        )
    ).all():
        accesses.setdefault(user_id, []).append(access)
    ranks = {user_id: rank_of(role, accesses.get(user_id, [])) for user_id, role in roles.items()}
    labels = {user_id: label_of(role, accesses.get(user_id, [])) for user_id, role in roles.items()}
    return ranks, labels


async def member_ranks(db: AsyncSession, org_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Rango de cada persona de la sede."""
    return (await member_ranks_and_labels(db, org_id))[0]


def scope_rank(scope: Scope) -> int:
    if scope.sees_everything:
        return RANK_ADMIN
    return rank_of("member", scope.access.values())


def can_assign_to(my_rank: int, my_id: uuid.UUID, target_id: uuid.UUID, target_rank: int) -> bool:
    return target_id == my_id or my_rank >= target_rank


async def users_who_can_see(db: AsyncSession, meeting: Meeting) -> list[uuid.UUID]:
    """Miembros de la sede que ven esta reunión: a quién mandarle avisos sobre ella."""
    private = (meeting.meta or {}).get("visibility", "org") == "private"
    conditions = [
        OrganizationMember.user_id == meeting.created_by,
        OrganizationMember.user_id.in_(
            select(MeetingShare.user_id).where(MeetingShare.meeting_id == meeting.id)
        ),
    ]
    conditions.append(
        OrganizationMember.user_id.in_(
            select(MeetingParticipant.user_id)
            .where(MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.user_id.is_not(None))
            .union(select(Speaker.user_id).where(Speaker.meeting_id == meeting.id, Speaker.user_id.is_not(None)))
        )
    )
    if meeting.kind == "interna":
        if meeting.group_id:
            conditions.append(
                OrganizationMember.user_id.in_(
                    select(InternalGroupMember.user_id).where(InternalGroupMember.group_id == meeting.group_id)
                )
            )
    else:
        conditions.append(OrganizationMember.role.in_(("admin", "owner")))
    if meeting.kind != "interna" and not private and meeting.family_id:
        conditions.append(
            OrganizationMember.user_id.in_(
                select(FamilyAssignment.user_id).where(FamilyAssignment.family_id == meeting.family_id)
            )
        )
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
    if meeting.kind != "interna" and not private and meeting.level:
        # La adviser del nivel se entera de lo que crea el DOE de ese nivel.
        creator_is_doe_row = (
            select(MemberLevelAccess.id)
            .where(
                MemberLevelAccess.organization_id == meeting.organization_id,
                MemberLevelAccess.user_id == meeting.created_by,
                MemberLevelAccess.level == meeting.level,
                MemberLevelAccess.access.in_(DOE_ACCESS),
            )
            .exists()
        )
        conditions.append(
            and_(
                OrganizationMember.user_id.in_(
                    select(MemberLevelAccess.user_id).where(
                        MemberLevelAccess.organization_id == meeting.organization_id,
                        MemberLevelAccess.level == meeting.level,
                        MemberLevelAccess.access == ADVISER_ACCESS,
                    )
                ),
                creator_is_doe_row,
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
    """La regla sin el compartido ni la presencia (que necesitan la base). Espejo de meeting_filter."""
    if meeting.created_by == scope.user_id:
        return True
    if meeting.kind == "interna":
        return meeting.group_id is not None and meeting.group_id in scope.groups
    if scope.sees_everything:
        return True
    private = (meeting.meta or {}).get("visibility", "org") == "private"
    if private:
        return False
    return meeting.level in scope.full_levels or (
        meeting.family_id is not None and meeting.family_id in scope.families
    )
