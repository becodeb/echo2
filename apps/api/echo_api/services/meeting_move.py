"""Mover una reunión a otra organización (sede). Solo superadmin.

Existe para corregir reuniones grabadas en la organización equivocada (por
ejemplo, alguien que todavía no estaba en su sede y se creó una propia). Se
mueve todo lo que es de la reunión; se suelta lo que pertenece a la
organización vieja y no tiene sentido en la nueva.

- Se mueven: transcript, hablantes, acta y sus versiones, resúmenes, temas,
  decisiones, tareas, preguntas, riesgos, comentarios y links compartidos.
  Las tablas con `organization_id` y FK a meetings se actualizan todas: se
  descubren del modelo, así una tabla nueva no queda en la sede vieja.
- Se sueltan: familia y motivo (son listas de la otra sede), proyectos,
  reuniones relacionadas, asistencia de integrantes y profesionales, y
  hechos de memoria (cuelgan de entidades de la otra sede).
- El acta pierde el número (era de la numeración de la otra sede) y la
  plantilla: al regenerarla sale con el formato de la sede nueva.

No hace commit.
"""
import uuid

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Base,
    Meeting,
    MeetingAttendance,
    MeetingLink,
    MeetingProfessionalAttendance,
    MemoryRelation,
    Minutes,
    ProjectMeeting,
)

# Se borran en vez de moverse: apuntan a cosas de la organización vieja.
_DROPPED = (MemoryRelation, ProjectMeeting, MeetingAttendance, MeetingProfessionalAttendance)


def _tables_to_move():
    """Tablas con organization_id y FK a meetings.meeting_id (salvo las que se sueltan)."""
    dropped = {model.__table__.name for model in _DROPPED}
    for table in Base.metadata.tables.values():
        if table.name in dropped or "organization_id" not in table.c or "meeting_id" not in table.c:
            continue
        if any(fk.column.table.name == "meetings" for fk in table.c.meeting_id.foreign_keys):
            yield table


async def move_meeting(db: AsyncSession, meeting: Meeting, target_org_id: uuid.UUID, level: str | None) -> None:
    for model in _DROPPED:
        await db.execute(delete(model).where(model.meeting_id == meeting.id))
    await db.execute(
        delete(MeetingLink).where(
            or_(MeetingLink.meeting_id == meeting.id, MeetingLink.related_meeting_id == meeting.id)
        )
    )
    for table in _tables_to_move():
        await db.execute(
            update(table).where(table.c.meeting_id == meeting.id).values(organization_id=target_org_id)
        )
    await db.execute(
        update(Minutes)
        .where(Minutes.meeting_id == meeting.id)
        .values(number=None, number_series=None, template_id=None)
    )
    meeting.organization_id = target_org_id
    meeting.family_id = None
    meeting.reason_id = None
    meeting.level = level
    await db.flush()
