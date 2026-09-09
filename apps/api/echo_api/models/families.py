"""Familias, motivos de reunión y asistencia.

Este es el vocabulario del caso de uso institucional: una organización tiene
familias, cada reunión se hace *con* una familia, por un motivo de una lista
que la propia organización define, con una gravedad, y con una asistencia que
se registra tutor por tutor.

Por qué la asistencia es una tabla y no un booleano en la reunión: la pregunta
real no es "¿vinieron todos?" sino "¿quién faltó, y falta seguido?". Con un
booleano esa segunda pregunta no se puede contestar nunca más.
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PKMixin, SoftDeleteMixin, TimestampMixin

# Vínculo de un integrante con la familia. "tutor" cubre abuelos, tíos y
# cualquier adulto responsable que no sea madre o padre.
RELATIONSHIPS = ("madre", "padre", "tutor", "estudiante", "otro")

# Semáforo. Se guarda el color y no un número para que dos personas puntúen
# igual: "amarillo" admite menos interpretación que "3 sobre 5".
SEVERITIES = ("verde", "amarillo", "rojo")

# Con quién es la reunión. En la práctica suele ser O con la familia O con los
# profesionales, por eso son opciones y no una combinación libre; "mixta"
# existe para la vez que sí están todos juntos.
AUDIENCES = ("familia", "profesionales", "mixta", "docentes", "interna")


class Family(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "families"
    __table_args__ = (Index("ix_families_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Legajo, matrícula o como lo llame la institución.
    reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    # Carpeta de Drive de la familia: informes, contexto, historia. Echo no
    # la lee ni la sincroniza, solo guarda el enlace para tenerlo a mano
    # desde la familia y desde cada reunión suya.
    drive_url: Mapped[str | None] = mapped_column(String(600))

    members: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )


class FamilyMember(PKMixin, TimestampMixin, Base):
    __tablename__ = "family_members"
    __table_args__ = (Index("ix_family_members_family", "family_id"),)

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(20), default="tutor", nullable=False)
    # Solo los marcados como responsables cuentan para "¿estuvieron todos?".
    # Un hermano mayor puede figurar en la familia sin que su ausencia cuente.
    is_guardian: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))

    family: Mapped["Family"] = relationship(back_populates="members")


class MeetingReason(PKMixin, TimestampMixin, Base):
    """Motivo de reunión. Lista cerrada por organización, no texto libre."""

    __tablename__ = "meeting_reasons"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_meeting_reason_name"),
        Index("ix_meeting_reasons_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Se desactiva en vez de borrarse: las reuniones viejas tienen que seguir
    # mostrando el motivo con el que se cargaron.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MeetingAttendance(PKMixin, TimestampMixin, Base):
    """Quién de la familia estuvo en una reunión."""

    __tablename__ = "meeting_attendance"
    __table_args__ = (
        UniqueConstraint("meeting_id", "family_member_id", name="uq_meeting_attendance"),
        Index("ix_meeting_attendance_meeting", "meeting_id"),
        Index("ix_meeting_attendance_member", "family_member_id"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    family_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("family_members.id", ondelete="CASCADE"), nullable=False
    )
    attended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Professional(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Terapeuta, acompañante, docente externo: alguien que no es de la familia.

    Vive a nivel organización y no dentro de una familia porque el mismo
    profesional suele acompañar a varias. Cargarlo una vez es lo que permite
    después preguntar "¿a cuántas familias ve?" o "¿en qué reuniones estuvo?".
    """

    __tablename__ = "professionals"
    __table_args__ = (Index("ix_professionals_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Terapeuta ocupacional, psicopedagoga, fonoaudióloga, docente…
    role_label: Mapped[str | None] = mapped_column(String(120))
    # Institución a la que pertenece, si no es de la organización.
    affiliation: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FamilyProfessional(PKMixin, TimestampMixin, Base):
    """Qué profesionales acompañan a una familia."""

    __tablename__ = "family_professionals"
    __table_args__ = (
        UniqueConstraint("family_id", "professional_id", name="uq_family_professional"),
        Index("ix_family_professionals_family", "family_id"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )


class MeetingProfessionalAttendance(PKMixin, TimestampMixin, Base):
    """Qué profesionales estuvieron en una reunión.

    Tabla aparte de la asistencia familiar a propósito: "vinieron todos los
    responsables" es una pregunta sobre la familia, y mezclar profesionales
    ahí adentro la contestaría mal.
    """

    __tablename__ = "meeting_professional_attendance"
    __table_args__ = (
        UniqueConstraint("meeting_id", "professional_id", name="uq_meeting_professional"),
        Index("ix_meeting_professional_meeting", "meeting_id"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )
    attended: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
