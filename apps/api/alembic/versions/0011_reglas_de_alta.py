"""Reglas de alta sin invitación por organización (dominios o emails).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 hace create_all con los modelos actuales: en una base nueva la
    # columna ya existe cuando llega esta migración.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "join_rules" not in columns:
        op.add_column("organizations", sa.Column("join_rules", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "join_rules")
