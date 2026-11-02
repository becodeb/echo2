"""Agenda en el calendario de cada uno: la clave que firma su enlace.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organization_members")}
    if "calendar_key" not in columns:
        op.add_column("organization_members", sa.Column("calendar_key", sa.String(24)))


def downgrade() -> None:
    op.drop_column("organization_members", "calendar_key")
