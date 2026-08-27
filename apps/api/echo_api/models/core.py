"""Usuarios, organizaciones, membresías, invitaciones, refresh tokens."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PKMixin, SoftDeleteMixin, TimestampMixin

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER)


class User(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(16), default="#6366f1")
    job_title: Mapped[str | None] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(String(10), default="es")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="user")


class Organization(PKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    members: Mapped[list["OrganizationMember"]] = relationship(back_populates="organization")


class OrganizationMember(PKMixin, TimestampMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default=ROLE_MEMBER, nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class OrganizationInvite(PKMixin, TimestampMixin, Base):
    __tablename__ = "organization_invites"
    __table_args__ = (Index("ix_org_invites_org", "organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_MEMBER)
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True, nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(PKMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(400))
