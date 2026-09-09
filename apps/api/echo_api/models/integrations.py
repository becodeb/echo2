"""Integraciones externas de una organización.

Por ahora solo Google Drive. El refresh token va cifrado con la misma clave
Fernet que el resto de los secretos: es lo que permite subir archivos en
nombre de la organización sin que nadie tenga que reconectarse cada vez.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin


class OrgGoogleDrive(PKMixin, TimestampMixin, Base):
    """Conexión a Google Drive de una organización.

    El alcance pedido es `drive.file`: Echo solo ve y toca lo que él mismo
    creó. No puede leer el Drive de la institución, y eso es deliberado — el
    permiso amplio exige revisión de Google y daría acceso a todo.
    """

    __tablename__ = "organization_google_drive"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_google_drive"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    # Con qué cuenta se conectó: los archivos quedan a nombre de esa persona,
    # así que tiene que estar a la vista de quien administra.
    connected_email: Mapped[str | None] = mapped_column(String(320))
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Carpeta madre que crea Echo. Se puede mover a cualquier lado del Drive:
    # el acceso lo da haberla creado, no dónde esté.
    root_folder_id: Mapped[str | None] = mapped_column(String(120))
    root_folder_url: Mapped[str | None] = mapped_column(String(600))
    # Último error de subida, en castellano y para mostrar. Sin esto una
    # integración que dejó de funcionar es invisible hasta que alguien va a
    # buscar un acta a Drive y no está.
    last_error: Mapped[str | None] = mapped_column(String(400))


class ServerAISettings(PKMixin, TimestampMixin, Base):
    """Default de IA de toda la instalación, editable por el superadmin.

    Existe para que cambiar la key o el modelo del default no dependa de un
    redeploy ni de tocar variables de entorno: el superadmin lo carga desde el
    panel y aplica al instante a toda organización que no configuró la suya.

    Es una fila única. Gana sobre las variables de entorno, que quedan como
    piso para una instalación recién levantada.
    """

    __tablename__ = "server_ai_settings"

    llm_provider: Mapped[str | None] = mapped_column(String(40))
    llm_model: Mapped[str | None] = mapped_column(String(120))
    llm_api_key_enc: Mapped[str | None] = mapped_column(Text)
    llm_base_url: Mapped[str | None] = mapped_column(String(300))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
