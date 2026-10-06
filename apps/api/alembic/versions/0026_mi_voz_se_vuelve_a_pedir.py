""""Mi voz" se vuelve a pedir a todos los que no la grabaron, ahora sin cruz ni
"Ahora no": la invitación se cierra grabando o con "No volver a mostrar".

Quien eligió "No volver a mostrar" con la versión anterior lo hizo pudiendo
cerrarla; se le vuelve a mostrar una vez más (Bauti, 6/10).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-06
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET voice_prompt_seen_at = NULL")


def downgrade() -> None:
    pass
