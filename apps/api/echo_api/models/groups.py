"""Grupos internos: directivos, coordinadores y los que arme cada sede.

Las reuniones internas (sin familia de por medio) son de un grupo, y las ve
quien es del grupo. No alcanza con ser admin: una secretaria que administra la
sede no ve las reuniones de directivos salvo que la sumen al grupo, y sumarse
queda en el log de auditoría. La regla vive en services/access.py.
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PKMixin, TimestampMixin

# Los que se crean solos la primera vez que una sede entra a Reuniones internas.
DEFAULT_GROUPS = ("Directivos", "Coordinadores")


class InternalGroup(PKMixin, TimestampMixin, Base):
    __tablename__ = "internal_groups"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_internal_group_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class InternalGroupMember(PKMixin, TimestampMixin, Base):
    __tablename__ = "internal_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_internal_group_member"),
        Index("ix_internal_group_members_org_user", "organization_id", "user_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("internal_groups.id", ondelete="CASCADE"), nullable=False
    )
    # Repetido del grupo para cargar "de qué grupos soy en esta sede" sin join.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
