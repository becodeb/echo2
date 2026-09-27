"""Muestra de voz de una persona, para reconocerla por nombre en las reuniones.

Es un audio corto (hasta 10 s, WAV 16 kHz mono) que la persona graba ella
misma en Ajustes → Mi voz, con su consentimiento explícito, y puede borrar
cuando quiera. Se le pasa al modelo que separa hablantes como "voz conocida"
(services/diarization.py): así en el transcript aparece su nombre en vez de
"Persona 2". No se usa para nada más.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, UniqueConstraint
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
