"""Agente de voz: server_ai_settings.voice_agent_id.

El agente de ElevenLabs de la conversación por voz (plan Individual + voz) lo
crea un superadmin desde el panel; su id queda acá para no depender de un
redeploy.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("server_ai_settings")}
    if "voice_agent_id" not in columns:
        op.add_column("server_ai_settings", sa.Column("voice_agent_id", sa.String(80)))


def downgrade() -> None:
    op.drop_column("server_ai_settings", "voice_agent_id")
