"""Rayas del formulario elegidas por cada persona (Mi cuenta → Mis actas).

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "acta_lines" not in columns:
        op.add_column("users", sa.Column("acta_lines", sa.String(3), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "acta_lines")
