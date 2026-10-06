"""Las tareas que detectó Echo antes del 5/10 quedaron sin persona (solo un
nombre como "la Directora"), así que no aparecían en Mi trabajo de nadie. Se
pasan a quien grabó la reunión, como las nuevas (0025); lo que había dicho la
IA queda como sugerencia.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-06
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE action_items AS task
        SET suggested_assignee = COALESCE(task.suggested_assignee, task.assignee_name),
            assignee_user_id = meetings.created_by,
            assignee_name = users.name
        FROM meetings
        JOIN users ON users.id = meetings.created_by
        WHERE meetings.id = task.meeting_id
          AND task.assignee_user_id IS NULL
          AND task.source = 'ai'
        """
    )


def downgrade() -> None:
    # No se distingue cuáles se pasaron acá de las que se repartieron después.
    pass
