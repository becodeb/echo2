"""A quién van las tareas que detecta la IA.

A quien grabó la reunión: es quien sabe qué se acordó y las reparte entre las
personas de la sede (routers/tasks.py). Quién dijo en la reunión que se
encargaba queda como sugerencia. Las reuniones de un Echo Device no tienen
quien grabó: quedan sin asignar, con la sugerencia.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Meeting, User


async def task_owner(db: AsyncSession, meeting: Meeting) -> tuple[uuid.UUID | None, str | None]:
    if meeting.created_by is None:
        return None, None
    user = await db.get(User, meeting.created_by)
    if user is None:
        return None, None
    return user.id, user.name
