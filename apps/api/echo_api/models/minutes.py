"""Actas: documento, versiones y plantillas."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin

MINUTES_STATUS = ("draft", "in_review", "approved")


class MinutesTemplate(PKMixin, TimestampMixin, Base):
    """Plantilla de acta de la organización.

    El contenido es Markdown estructurado con secciones. Cuando el usuario
    proporcione su MODELO REAL de acta, se carga acá y pasa a ser la
    source of truth del generador. El template default que se instala en el
    seed está claramente marcado como provisional.
    """

    __tablename__ = "minutes_templates"
    __table_args__ = (Index("ix_minutes_templates_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=True)


class Minutes(PKMixin, TimestampMixin, Base):
    """Acta de una reunión. El contenido vive en las versiones."""

    __tablename__ = "minutes"
    __table_args__ = (Index("ix_minutes_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|in_review|approved
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    # Estado del generador, separado del estado editorial de arriba. Sin esto
    # una generación que falla queda invisible y la UI espera para siempre.
    generation_status: Mapped[str] = mapped_column(
        String(20), default="idle", nullable=False
    )  # idle|generating|ok|failed
    # Motivo en castellano y apto para mostrar. El detalle técnico va al log.
    generation_error: Mapped[str | None] = mapped_column(String(400))
    generation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minutes_templates.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MinutesVersion(PKMixin, TimestampMixin, Base):
    __tablename__ = "minutes_versions"
    __table_args__ = (Index("ix_minutes_versions_minutes", "minutes_id", "version"),)

    minutes_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("minutes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Markdown del acta completa
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    # Bloques anotados: [{id, kind, origin: "ai"|"human", text, evidence: [{start_ms, end_ms}]}]
    blocks: Mapped[list | None] = mapped_column(JSONB)
    # Resultado del verificador: [{claim, status: "verified"|"weak"|"missing", evidence_ms}]
    verification: Mapped[list | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(300))  # "automática", "editada por Ana"
    model_used: Mapped[str | None] = mapped_column(String(120))
