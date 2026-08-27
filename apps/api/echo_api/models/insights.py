"""Información estructurada extraída de reuniones."""
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin


class MeetingTopic(PKMixin, TimestampMixin, Base):
    __tablename__ = "meeting_topics"
    __table_args__ = (Index("ix_topics_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)


class Decision(PKMixin, TimestampMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_meeting", "meeting_id"),
        Index("ix_decisions_org", "organization_id"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)  # por qué se decidió
    evidence_start_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_end_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|superseded
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai|manual


class ActionItem(PKMixin, TimestampMixin, Base):
    __tablename__ = "action_items"
    __table_args__ = (
        Index("ix_action_items_meeting", "meeting_id"),
        Index("ix_action_items_org_status", "organization_id", "status"),
    )

    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_name: Mapped[str | None] = mapped_column(String(200))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    due_text: Mapped[str | None] = mapped_column(String(120))  # "viernes"
    due_date: Mapped[date | None] = mapped_column(Date)  # 2026-08-28 (resuelta)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|in_progress|done|cancelled
    evidence_start_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_end_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="ai")


class Question(PKMixin, TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_start_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_end_ms: Mapped[int | None] = mapped_column(Integer)


class Risk(PKMixin, TimestampMixin, Base):
    __tablename__ = "risks"
    __table_args__ = (Index("ix_risks_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_start_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_end_ms: Mapped[int | None] = mapped_column(Integer)


class MeetingSummary(PKMixin, TimestampMixin, Base):
    __tablename__ = "meeting_summaries"
    __table_args__ = (Index("ix_summaries_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # executive|detailed|timeline|section
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)  # estructura según kind
    model_used: Mapped[str | None] = mapped_column(String(120))
