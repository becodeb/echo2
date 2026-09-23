"""Nombres protegidos: nómina que se reemplaza por marcadores antes de la IA.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 hace create_all con los modelos actuales: en una base nueva la
    # tabla ya existe cuando llega esta migración (misma guarda que 0004/0005).
    inspector = sa.inspect(op.get_bind())
    if "organization_protected_names" in set(inspector.get_table_names()):
        return
    op.create_table(
        "organization_protected_names",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="persona"),
        sa.Column("group_key", sa.String(200), nullable=True),
        sa.Column("extra", JSONB(), nullable=True),
        sa.Column("source", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_org_protected_names_org", "organization_protected_names", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_org_protected_names_org", table_name="organization_protected_names")
    op.drop_table("organization_protected_names")
