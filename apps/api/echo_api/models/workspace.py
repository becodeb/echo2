"""Proyectos, comentarios, sharing, dispositivos, settings IA, auditoría, memoria."""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, SoftDeleteMixin, TimestampMixin
from .meetings import EMBEDDING_DIM


class Project(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|archived
    color: Mapped[str] = mapped_column(String(16), default="#6366f1")


class ProjectMeeting(PKMixin, TimestampMixin, Base):
    __tablename__ = "project_meetings"
    __table_args__ = (
        UniqueConstraint("project_id", "meeting_id", name="uq_project_meeting"),
        Index("ix_project_meetings_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )


class Comment(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Comentarios anclados a un objeto: acta, segmento, decisión o tarea."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_target", "target_type", "target_id"),
        Index("ix_comments_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)  # minutes_block|segment|decision|action_item
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list | None] = mapped_column(JSONB)  # [user_id, ...]
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class SharedLink(PKMixin, TimestampMixin, Base):
    __tablename__ = "shared_links"
    __table_args__ = (Index("ix_shared_links_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer|commenter
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allow_download: Mapped[bool] = mapped_column(Boolean, default=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)


class MeetingShare(PKMixin, TimestampMixin, Base):
    """ACL por usuario sobre una reunión (además de la visibilidad org)."""

    __tablename__ = "meeting_shares"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_share"),
        Index("ix_meeting_shares_user", "user_id"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer|commenter|editor|admin
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Device(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Echo Device (ESP32 u otro hardware)."""

    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="esp32")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(40))
    available_version: Mapped[str | None] = mapped_column(String(40))  # para OTA futuro
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_state: Mapped[dict | None] = mapped_column(JSONB)  # {wifi_rssi, status, ...}


class DevicePairCode(PKMixin, TimestampMixin, Base):
    __tablename__ = "device_pair_codes"

    code: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    device_kind: Mapped[str] = mapped_column(String(40), default="esp32")
    device_info: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    # token temporal que el dispositivo usa para hacer polling del pairing
    poll_token: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)


class OrgAISettings(PKMixin, TimestampMixin, Base):
    """Configuración de IA por organización. Las API keys van cifradas (Fernet)."""

    __tablename__ = "organization_ai_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_ai_settings"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # LLM
    llm_provider: Mapped[str | None] = mapped_column(String(40))  # openai|anthropic|gemini|groq|openrouter|ollama
    llm_model: Mapped[str | None] = mapped_column(String(120))
    llm_api_key_enc: Mapped[str | None] = mapped_column(Text)
    llm_base_url: Mapped[str | None] = mapped_column(String(300))
    llm_temperature: Mapped[str | None] = mapped_column(String(10))
    # STT cloud fallback
    stt_provider: Mapped[str | None] = mapped_column(String(40))  # bridge|openai|groq|deepgram
    stt_model: Mapped[str | None] = mapped_column(String(120))
    stt_api_key_enc: Mapped[str | None] = mapped_column(Text)
    # Embeddings
    embeddings_provider: Mapped[str | None] = mapped_column(String(40))  # openai|ollama|none
    embeddings_model: Mapped[str | None] = mapped_column(String(120))
    embeddings_api_key_enc: Mapped[str | None] = mapped_column(Text)
    # Diarización
    diarization_provider: Mapped[str | None] = mapped_column(String(40))  # local_onnx|none
    # Idioma del acta (puede diferir del hablado)
    minutes_language: Mapped[str] = mapped_column(String(10), default="es")
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)


class OrgDictionaryEntry(PKMixin, TimestampMixin, Base):
    """Diccionario personalizado: vocabulary bias para STT y contexto para el LLM."""

    __tablename__ = "organization_dictionary"
    __table_args__ = (
        UniqueConstraint("organization_id", "term", name="uq_org_dict_term"),
        Index("ix_org_dictionary_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="term")  # term|person|product|acronym|vendor
    note: Mapped[str | None] = mapped_column(String(300))


class AuditLog(PKMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)  # meeting.share, minutes.approve, ...
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))


class Notification(PKMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # minutes_ready|task_assigned|comment|minutes_approved
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(400))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryEntity(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Memoria estructurada entre reuniones: proyectos, personas, temas, hechos."""

    __tablename__ = "memory_entities"
    __table_args__ = (
        UniqueConstraint("organization_id", "kind", "normalized_name", name="uq_memory_entity"),
        Index("ix_memory_entities_org_kind", "organization_id", "kind"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # project|person|topic|date|number|link
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)  # estado actual consolidado
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class MemoryRelation(PKMixin, TimestampMixin, Base):
    """Relación entidad ↔ hecho ↔ reunión. La evidencia siempre apunta al transcript."""

    __tablename__ = "memory_relations"
    __table_args__ = (
        Index("ix_memory_relations_entity", "entity_id"),
        Index("ix_memory_relations_meeting", "meeting_id"),
        Index("ix_memory_relations_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE")
    )
    relation: Mapped[str] = mapped_column(String(40), nullable=False)  # decided|mentioned|assigned|due|changed|relates_to
    # objeto de la relación: otra entidad o un item estructurado
    other_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE")
    )
    ref_type: Mapped[str | None] = mapped_column(String(30))  # decision|action_item|question|risk|segment
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fact: Mapped[str | None] = mapped_column(Text)  # texto del hecho
    happened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_start_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_end_ms: Mapped[int | None] = mapped_column(Integer)
