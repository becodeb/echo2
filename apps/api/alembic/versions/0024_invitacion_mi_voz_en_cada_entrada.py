"""La invitación a grabar "Mi voz" aparece en cada entrada hasta que se elige
"No volver a mostrar".

`users.voice_prompt_seen_at` pasa a significar eso. Hasta ahora se llenaba con
cerrar la invitación ("Ahora no"), que no es lo mismo: se vacía para que a
quien la cerró le vuelva a aparecer.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-05
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET voice_prompt_seen_at = NULL")


def downgrade() -> None:
    # No hay cómo saber quién la había cerrado: queda como está.
    pass
