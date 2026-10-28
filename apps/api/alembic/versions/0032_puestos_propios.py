"""Puestos propios de cada sede ("Adviser", "Tutora"...).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # El puesto propio se guarda con su id (36 caracteres).
    op.alter_column("organization_members", "position", type_=sa.String(40), existing_nullable=True)
    if "custom_positions" not in inspector.get_table_names():
        op.create_table(
            "custom_positions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("description", sa.String(200), server_default="", nullable=False),
            sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("access", sa.String(20), server_default="limitado", nullable=False),
            sa.Column(
                "group_id", postgresql.UUID(as_uuid=True),
                sa.ForeignKey("internal_groups.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column(
                "watch_group_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}", nullable=False
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "name", name="uq_custom_position_name"),
        )


def downgrade() -> None:
    op.drop_table("custom_positions")
