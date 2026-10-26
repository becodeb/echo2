"""Hijos de una familia con curso y nivel, y de qué hijo es cada reunión.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "curso" not in _columns("family_members"):
        op.add_column("family_members", sa.Column("curso", sa.String(60)))
    if "level" not in _columns("family_members"):
        op.add_column("family_members", sa.Column("level", sa.String(20)))
    if "student_ids" not in _columns("meetings"):
        op.add_column("meetings", sa.Column("student_ids", JSONB))


def downgrade() -> None:
    op.drop_column("meetings", "student_ids")
    op.drop_column("family_members", "level")
    op.drop_column("family_members", "curso")
