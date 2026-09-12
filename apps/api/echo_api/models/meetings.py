"""Reuniones, participantes, hablantes, transcript."""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PKMixin, SoftDeleteMixin, TimestampMixin

# Dimensión canónica de embeddings. Providers con dimensión menor se
# normalizan con zero-padding (preserva la similitud coseno).
EMBEDDING_DIM = 1536

MEETING_STATUS = ("draft", "live", "paused", "processing", "completed", "failed")


class Meeting(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_org_started", "organization_id", "started_at"),
        Index("ix_meetings_org_status", "organization_id", "status"),
        Index("ix_meetings_family", "family_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="es")
    audio_source: Mapped[str] = mapped_column(String(30), default="browser")  # browser|bridge|device|import
    stt_engine: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    processing_state: Mapped[dict] = mapped_column(JSONB, default=dict)  # progreso del pipeline
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Clasificación institucional de la reunión. Los tres son opcionales: una
    # reunión se puede grabar primero y clasificar después, y no toda reunión
    # es con una familia.
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="SET NULL")
    )
    reason_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_reasons.id", ondelete="SET NULL")
    )
    severity: Mapped[str | None] = mapped_column(String(10))  # verde|amarillo|rojo
    # Con quién fue: familia|profesionales|mixta|docentes|interna
    audience: Mapped[str | None] = mapped_column(String(20))

    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingParticipant(PKMixin, TimestampMixin, Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (
        UniqueConstraint("meeting_id", "name", name="uq_meeting_participant_name"),
        Index("ix_meeting_participants_meeting", "meeting_id"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    # user_id es opcional: un participante puede no tener cuenta en Echo
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    role_label: Mapped[str | None] = mapped_column(String(120))  # cargo

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")


class Speaker(PKMixin, TimestampMixin, Base):
    __tablename__ = "speakers"
    __table_args__ = (Index("ix_speakers_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(60), nullable=False)  # "Speaker 1"
    display_name: Mapped[str | None] = mapped_column(String(200))  # "Ana"
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="SET NULL")
    )
    color: Mapped[str] = mapped_column(String(16), default="#64748b")
    # sugerencia de voice profile: {profile_id, person_name, confidence}
    identity_suggestion: Mapped[dict | None] = mapped_column(JSONB)

    meeting: Mapped["Meeting"] = relationship(back_populates="speakers")


class SpeakerProfile(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Voice profile OPT-IN de una persona. Guarda solo el embedding, nunca audio.

    ⚠️ SCHEMA PREPARADO, SIN IMPLEMENTACIÓN. La tabla existe y la migración la
    crea, pero NINGÚN código la lee ni la escribe: no hay endpoint que dé de
    alta un perfil, no hay nada que calcule este embedding y el pipeline de
    finalización no consulta esta tabla. Identificar hablantes por voz
    requiere primero un extractor de embeddings de voz (ECAPA/pyannote o
    similar), que hoy no está en el repo.

    No la documentes como una feature viva ni asumas que hay datos acá.
    """

    __tablename__ = "speaker_profiles"
    __table_args__ = (Index("ix_speaker_profiles_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(256))
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TranscriptSegment(PKMixin, TimestampMixin, Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_segments_meeting_time", "meeting_id", "start_ms"),
        Index("ix_segments_meeting_seq", "meeting_id", "seq"),
        Index("ix_segments_tsv", "tsv", postgresql_using="gin"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("speakers.id", ondelete="SET NULL")
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)  # full-text search
    # ⚠️ TRAMPA DE AUTOGENERATE — LEER ANTES DE TOCAR MIGRACIONES ⚠️
    # El índice HNSW de esta columna (`ix_segments_embedding`) NO está
    # declarado acá: lo crea por SQL crudo `alembic/versions/0001_initial.py`,
    # porque el opclass `vector_cosine_ops` de pgvector no se expresa bien en
    # la capa declarativa de SQLAlchemy.
    # Consecuencia: `alembic revision --autogenerate` no lo ve en los modelos,
    # lo interpreta como índice borrado a mano y GENERA UN `drop_index`. Si esa
    # migración se aplica, la búsqueda semántica pasa a escaneo secuencial sin
    # un solo error visible — sólo se pone lenta.
    # `alembic check` ya reporta `Detected removed index` para este índice: es
    # ruido ESPERADO, no un drift que haya que "arreglar" declarándolo.
    # Si autogenerás: borrá a mano el `drop_index` del archivo resultante.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    topic: Mapped[str | None] = mapped_column(String(200))
    # hint de diarización en vivo (canal/cluster del bridge o dispositivo)
    speaker_hint: Mapped[str | None] = mapped_column(String(60))


class SegmentRevision(PKMixin, TimestampMixin, Base):
    """Historial de ediciones del transcript: conserva la versión original."""

    __tablename__ = "segment_revisions"
    __table_args__ = (Index("ix_segment_revisions_segment", "segment_id"),)

    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False
    )
    previous_text: Mapped[str] = mapped_column(Text, nullable=False)
    new_text: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Bookmark(PKMixin, TimestampMixin, Base):
    """Marcadores manuales durante la reunión: importante, nota, decisión, tarea."""

    __tablename__ = "bookmarks"
    __table_args__ = (Index("ix_bookmarks_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # important|note|decision|task|moment
    at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class MeetingLink(PKMixin, TimestampMixin, Base):
    """Relación entre reuniones (continuación, referencia)."""

    __tablename__ = "meeting_links"
    __table_args__ = (
        UniqueConstraint("meeting_id", "related_meeting_id", name="uq_meeting_link"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    related_meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), default="related")  # related|continues
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_reason: Mapped[str | None] = mapped_column(Text)


class MeetingAttachment(PKMixin, TimestampMixin, Base):
    """Enlace adjunto a una reunión: informe, carpeta de Drive, planilla.

    Solo la URL: Echo no guarda ni copia el archivo. Es a propósito, el
    material sensible sigue viviendo donde la institución ya lo tiene.
    """

    __tablename__ = "meeting_attachments"
    __table_args__ = (Index("ix_meeting_attachments_meeting", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
