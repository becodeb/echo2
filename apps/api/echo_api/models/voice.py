"""Muestra de voz de una persona, para reconocerla por nombre en las reuniones.

Es un audio corto (hasta 10 s, WAV 16 kHz mono) que la persona graba ella
misma en Mi voz, con su consentimiento explícito, y puede borrar cuando
quiera. De la muestra se saca una huella (services/voiceprint.py), en el
servidor de Echo, y después de cada reunión se compara con la de cada
persona que habló: así en el transcript aparece su nombre en vez de
"Persona 2". No se usa para nada más.

`embedding` es el perfil que se compara: la huella de la muestra y, si la
persona lo permite (`learn_from_meetings`), promediada con las de reuniones
donde se la reconoció con seguridad (§7.4).
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin


class UserVoiceSample(PKMixin, TimestampMixin, Base):
    __tablename__ = "user_voice_samples"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_voice_sample"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    audio_wav: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_embedding: Mapped[list[float] | None] = mapped_column(Vector(256))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(256))
    embedding_model: Mapped[str | None] = mapped_column(String(60))
    learned_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    learn_from_meetings: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
