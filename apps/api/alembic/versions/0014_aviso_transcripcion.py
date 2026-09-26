"""Aviso de una sola vez: la transcripción ahora es más precisa.

Una notificación de tipo anuncio para cada persona de cada sede. La web la
muestra como aviso emergente y al cerrarla se marca leída en todas sus sedes
(routers/notifications.py), así sale una sola vez por persona y nunca más.
Quien se registre después no la recibe: nunca conoció la transcripción vieja.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-26
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

KIND = "announcement:transcripcion_precisa"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO notifications (id, user_id, organization_id, kind, title, body, created_at, updated_at)
        SELECT gen_random_uuid(), m.user_id, m.organization_id, '{KIND}',
               'La transcripción ahora es mucho más precisa',
               'Echo ahora entiende mejor lo que se dice en las reuniones: se equivoca mucho menos y '
               'escribe bien los nombres y apellidos que tiene cargados. No tenés que hacer nada, '
               'ya está funcionando en tus próximas reuniones.',
               now(), now()
        FROM organization_members m
        JOIN users u ON u.id = m.user_id AND u.deleted_at IS NULL
        JOIN organizations o ON o.id = m.organization_id AND o.deleted_at IS NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM notifications n WHERE n.user_id = m.user_id AND n.kind = '{KIND}'
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE kind = '{KIND}'")
