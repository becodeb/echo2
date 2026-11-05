"""Opinión de los usuarios: los popups de estrellitas y de sugerencias."""
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin

FEEDBACK_KINDS = ("stars", "suggestion")


class FeedbackPrompt(TimestampMixin, Base):
    """Cómo se pregunta cada cosa. Sin fila, el default de routers/feedback.py (apagado)."""

    __tablename__ = "feedback_prompts"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    # Cada cuánto se le vuelve a preguntar a la misma persona.
    every_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class FeedbackResponse(PKMixin, TimestampMixin, Base):
    """Una respuesta, o un "Ahora no" (`dismissed`): los dos frenan la próxima pregunta."""

    __tablename__ = "feedback_responses"
    __table_args__ = (
        CheckConstraint("stars IS NULL OR stars BETWEEN 1 AND 5", name="ck_feedback_stars"),
        Index("ix_feedback_user_kind_created", "user_id", "kind", "created_at"),
        Index("ix_feedback_created", "created_at"),
    )
    __mapper_args__ = {"eager_defaults": True}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # La sede en la que estaba cuando respondió; nula si no estaba en ninguna.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    stars: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
