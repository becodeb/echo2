"""Reuniones internas por grupo, grabación opcional y Drive personal.

- meetings.kind (familia|interna) y meetings.group_id: las internas las ve su
  grupo (services/access.py). Todas las existentes quedan como "familia".
- internal_groups / internal_group_members.
- meetings.recording: estado de la grabación del audio completo.
- user_google_drive: Drive de cada persona, adonde van sus grabaciones.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 0001 hace create_all con los modelos actuales: en una base nueva todo
    # esto ya existe cuando llega esta migración.
    if "internal_groups" not in tables:
        op.create_table(
            "internal_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(80), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("organization_id", "name", name="uq_internal_group_name"),
        )
    if "internal_group_members" not in tables:
        op.create_table(
            "internal_group_members",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "group_id", UUID(as_uuid=True), sa.ForeignKey("internal_groups.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("group_id", "user_id", name="uq_internal_group_member"),
        )
        op.create_index(
            "ix_internal_group_members_org_user", "internal_group_members", ["organization_id", "user_id"]
        )
    if "user_google_drive" not in tables:
        op.create_table(
            "user_google_drive",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("refresh_token_enc", sa.Text, nullable=False),
            sa.Column("connected_email", sa.String(320)),
            sa.Column("connected_at", sa.DateTime(timezone=True)),
            sa.Column("folder_id", sa.String(120)),
            sa.Column("folder_url", sa.String(600)),
            sa.Column("last_error", sa.String(400)),
            *_timestamps(),
            sa.UniqueConstraint("user_id", name="uq_user_google_drive"),
        )

    columns = {column["name"] for column in inspector.get_columns("meetings")}
    if "kind" not in columns:
        op.add_column(
            "meetings", sa.Column("kind", sa.String(20), server_default="familia", nullable=False)
        )
    if "group_id" not in columns:
        op.add_column(
            "meetings",
            sa.Column(
                "group_id", UUID(as_uuid=True), sa.ForeignKey("internal_groups.id", ondelete="SET NULL")
            ),
        )
    if "recording" not in columns:
        op.add_column("meetings", sa.Column("recording", JSONB))
    if "ix_meetings_org_kind" not in {index["name"] for index in inspector.get_indexes("meetings")}:
        op.create_index("ix_meetings_org_kind", "meetings", ["organization_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_meetings_org_kind", table_name="meetings")
    op.drop_column("meetings", "recording")
    op.drop_column("meetings", "group_id")
    op.drop_column("meetings", "kind")
    op.drop_table("user_google_drive")
    op.drop_index("ix_internal_group_members_org_user", table_name="internal_group_members")
    op.drop_table("internal_group_members")
    op.drop_table("internal_groups")
