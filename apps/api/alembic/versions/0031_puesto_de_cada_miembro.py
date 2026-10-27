"""Puesto de cada miembro de la sede (DOE, docente, directivo...).

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("organization_members")}
    if "position" not in columns:
        op.add_column("organization_members", sa.Column("position", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("organization_members", "position")
