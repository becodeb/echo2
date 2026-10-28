"""Puestos: lo que elige quien administra la sede, en palabras de un colegio.

Un puesto no es un permiso nuevo: se traduce a lo que ya existe y decide
quién ve qué (services/access.py), así las reglas de visibilidad y de tareas
siguen siendo las mismas:

- rol de sede (`OrganizationMember.role`): admin para Dirección de la sede,
  member para el resto;
- acceso en cada nivel elegido (`MemberLevelAccess`): total, adviser,
  direccion, limitado o tutor; en los niveles no elegidos, ninguno;
- grupo interno (`InternalGroup`): el de las reuniones internas del puesto.

El puesto se guarda (`OrganizationMember.position`) porque DOE, docente y
secretaría dan los mismos permisos y no se pueden deducir. Si después alguien
toca un acceso a mano desde Niveles y accesos, manda el acceso: el puesto es
solo el nombre.

Además de los seis fijos, cada sede puede armar los suyos (CustomPosition:
"Adviser", "Tutora"...). Se traducen igual y pueden sumar un permiso más: ver
las reuniones de los integrantes de ciertos grupos (services/access.py).
"""
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CustomPosition, InternalGroup


@dataclass(frozen=True)
class Position:
    id: str
    label: str
    # Rol de sede que le corresponde.
    role: str
    # Acceso en cada nivel elegido.
    access: str
    # Grupo interno al que se lo suma (se crea si la sede no lo tiene).
    group: str | None
    description: str
    # Solo los propios de la sede: se pueden editar y borrar.
    custom: bool = False
    # Grupos cuyas reuniones también ve (solo los propios).
    watch_group_ids: tuple[uuid.UUID, ...] = field(default=())


POSITIONS: tuple[Position, ...] = (
    Position(
        "direccion_sede", "Dirección de la sede", "admin", "direccion", "Directivos",
        "Ve todo y administra la sede, sus usuarios y ajustes.",
    ),
    Position(
        "directivo", "Directivo", "member", "direccion", "Directivos",
        "Ve lo suyo y sus familias, y asigna DOE y tutores en su nivel.",
    ),
    Position(
        "coordinacion", "Coordinación", "member", "total", "Coordinadores",
        "Ve todas las reuniones de su nivel.",
    ),
    Position(
        "adviser", "Adviser", "member", "adviser", None,
        "Jefa de las coordinadoras del DOE: ve lo suyo y lo que crea el DOE y los tutores de su nivel.",
    ),
    Position(
        "doe", "DOE", "member", "limitado", "DOE",
        "Ve lo suyo, sus familias, donde estuvo y las reuniones internas del DOE.",
    ),
    Position(
        "tutor", "Tutor/a", "member", "tutor", "DOE",
        "Igual que el DOE: lo suyo, sus familias, donde estuvo y las reuniones internas del DOE.",
    ),
    Position(
        "docente", "Docente", "member", "limitado", None,
        "Ve lo suyo, sus familias y donde estuvo.",
    ),
    Position(
        "secretaria", "Secretaría / Administración", "member", "limitado", None,
        "Ve lo suyo y donde estuvo.",
    ),
)

BY_ID = {position.id: position for position in POSITIONS}


async def org_positions(db: AsyncSession, org_id: uuid.UUID) -> list[Position]:
    """Los fijos y los propios de la sede, en el orden en que se muestran."""
    rows = (
        await db.execute(
            select(CustomPosition, InternalGroup.name)
            .outerjoin(InternalGroup, InternalGroup.id == CustomPosition.group_id)
            .where(CustomPosition.organization_id == org_id)
            .order_by(CustomPosition.name)
        )
    ).all()
    return [*POSITIONS, *(custom_position(row, group) for row, group in rows)]


def custom_position(row: CustomPosition, group: str | None) -> Position:
    return Position(
        str(row.id), row.name, "admin" if row.is_admin else "member", row.access, group, row.description,
        custom=True, watch_group_ids=tuple(row.watch_group_ids or ()),
    )


def is_admin_role(role: str) -> bool:
    return role in ("admin", "owner")


def guess_position(role: str, accesses: list[str], groups: set[str]) -> str | None:
    """El puesto que parece tener alguien a quien nadie se lo eligió: solo para mostrarlo."""
    if is_admin_role(role):
        return "direccion_sede"
    if "direccion" in accesses:
        return "directivo"
    if "adviser" in accesses:
        return "adviser"
    if "total" in accesses:
        return "coordinacion"
    if "DOE" in groups:
        return "tutor" if "tutor" in accesses else "doe"
    if "tutor" in accesses:
        return "tutor"
    if "limitado" in accesses:
        return "docente"
    return None
