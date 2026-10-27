"""Puestos: lo que elige quien administra la sede, en palabras de un colegio.

Un puesto no es un permiso nuevo: se traduce a lo que ya existe y decide
quién ve qué (services/access.py), así las reglas de visibilidad y de tareas
siguen siendo las mismas:

- rol de sede (`OrganizationMember.role`): admin para Dirección de la sede,
  member para el resto;
- acceso en cada nivel elegido (`MemberLevelAccess`): direccion, total o
  limitado; en los niveles no elegidos, ninguno;
- grupo interno (`InternalGroup`): el de las reuniones internas del puesto.

El puesto se guarda (`OrganizationMember.position`) porque DOE, docente y
secretaría dan los mismos permisos y no se pueden deducir. Si después alguien
toca un acceso a mano desde Niveles y accesos, manda el acceso: el puesto es
solo el nombre.
"""
from dataclasses import dataclass


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


POSITIONS: tuple[Position, ...] = (
    Position(
        "direccion_sede", "Dirección de la sede", "admin", "direccion", "Directivos",
        "Ve todo y administra la sede, sus usuarios y ajustes.",
    ),
    Position(
        "directivo", "Directivo", "member", "direccion", "Directivos",
        "Ve todo su nivel y asigna quién ve qué en él.",
    ),
    Position(
        "coordinacion", "Coordinación", "member", "total", "Coordinadores",
        "Ve todas las reuniones de su nivel.",
    ),
    Position(
        "doe", "DOE", "member", "limitado", "DOE",
        "Ve lo suyo, sus familias, donde estuvo y las reuniones internas del DOE.",
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


def is_admin_role(role: str) -> bool:
    return role in ("admin", "owner")


def guess_position(role: str, accesses: list[str], groups: set[str]) -> str | None:
    """El puesto que parece tener alguien a quien nadie se lo eligió: solo para mostrarlo."""
    if is_admin_role(role):
        return "direccion_sede"
    if "direccion" in accesses:
        return "directivo"
    if "total" in accesses:
        return "coordinacion"
    if "DOE" in groups:
        return "doe"
    if "limitado" in accesses:
        return "docente"
    return None
