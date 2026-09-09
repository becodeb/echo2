"""Conexión a Google Drive por organización y rastro de subida del acta.

Mismo criterio que las anteriores: 0001 arma el schema con create_all() desde
los modelos, así que en una base nueva esto ya existe. Se inspecciona antes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "organization_google_drive" not in set(inspector.get_table_names()):
        op.create_table(
            "organization_google_drive",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("refresh_token_enc", sa.Text(), nullable=False),
            sa.Column("connected_email", sa.String(320), nullable=True),
            sa.Column("connected_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("root_folder_id", sa.String(120), nullable=True),
            sa.Column("root_folder_url", sa.String(600), nullable=True),
            sa.Column("last_error", sa.String(400), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("organization_id", name="uq_org_google_drive"),
        )

    minutes_columns = {c["name"] for c in inspector.get_columns("minutes")}
    if "drive_file_url" not in minutes_columns:
        op.add_column("minutes", sa.Column("drive_file_url", sa.String(600), nullable=True))
    if "drive_synced_version" not in minutes_columns:
        op.add_column("minutes", sa.Column("drive_synced_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("minutes", "drive_synced_version")
    op.drop_column("minutes", "drive_file_url")
    op.drop_table("organization_google_drive")
