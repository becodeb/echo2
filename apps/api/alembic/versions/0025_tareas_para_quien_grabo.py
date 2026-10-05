"""Tareas: se asignan a quien grabó la reunión, que después las reparte. Quién
dijo en la reunión que se iba a encargar queda como sugerencia
(`action_items.suggested_assignee`), y es lo que va al acta.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("action_items")}
    if "suggested_assignee" not in columns:
        op.add_column("action_items", sa.Column("suggested_assignee", sa.String(200)))


def downgrade() -> None:
    op.drop_column("action_items", "suggested_assignee")
