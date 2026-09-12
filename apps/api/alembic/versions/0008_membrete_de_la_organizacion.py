"""Membrete de la organización para el acta impresa (logo, dirección, etc.).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "letterhead" not in existing:
        op.add_column("organizations", sa.Column("letterhead", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "letterhead")
