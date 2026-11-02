"""Agenda: reuniones agendadas para un día, con todo cargado de antemano.

El día de la reunión se toca "Empezar" y la reunión nace con la familia, el
alumno, el motivo, el nivel y quiénes del colegio están. La hora es opcional:
alcanza con el día (pedido de Nordelta, 02/11/2026).
"""
import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin

# agendada: todavía no se hizo (o se está haciendo: lo dice la reunión enlazada).
# no_se_hizo: quien la agendó la descartó sin hacerla.
SCHEDULE_STATUSES = ("agendada", "no_se_hizo")


class ScheduledMeeting(PKMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_meetings"
    __table_args__ = (Index("ix_scheduled_meetings_org_date", "organization_id", "date"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # "HH:MM" o nada: muchas se agendan solo por día.
    time: Mapped[str | None] = mapped_column(String(5))
    # familia | interna (de un grupo), como Meeting.kind.
    kind: Mapped[str] = mapped_column(String(20), default="familia", nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="SET NULL")
    )
    student_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    reason_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_reasons.id", ondelete="SET NULL")
    )
    level: Mapped[str | None] = mapped_column(String(20))
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("internal_groups.id", ondelete="SET NULL")
    )
    # Quiénes del colegio van (además de quien la agenda): les aparece en su agenda.
    staff_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Para ese día ("traer el informe"): no va al acta.
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="agendada", nullable=False)
    # La reunión que se grabó al tocar "Empezar".
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL")
    )
