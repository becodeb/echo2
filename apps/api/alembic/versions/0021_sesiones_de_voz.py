"""Voz controlada por el servidor (docs/plan-correcciones.md §2.1 y §2.9).

- voice_sessions: cada charla que el servidor entrega (quién, cuánto puede
  durar, con qué agente, cuándo vence si nadie la cierra, y la conversación
  de ElevenLabs cuando se concilia). De a una abierta por persona.
- server_ai_settings.voice_agents: un agente por duración máxima (60, 180 y
  600 s): ElevenLabs no deja cambiar la duración por conversación, así que el
  tope de cada charla se elige eligiendo el agente. voice_agent_hash: la
  configuración con la que se crearon, para no actualizarlos en cada arranque.
- Plan Individual + voz: 30 minutos por mes (Bauti, 1/10: 52% de margen en
  el peor caso).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "voice_sessions" not in inspector.get_table_names():
        op.create_table(
            "voice_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
            sa.Column("allowed_seconds", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.String(80), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("conversation_id", sa.String(120), unique=True),
            sa.Column("seconds", sa.Float()),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_voice_sessions_user_created", "voice_sessions", ["user_id", "created_at"])
    columns = {column["name"] for column in inspector.get_columns("server_ai_settings")}
    if "voice_agents" not in columns:
        op.add_column("server_ai_settings", sa.Column("voice_agents", JSONB))
    if "voice_agent_hash" not in columns:
        op.add_column("server_ai_settings", sa.Column("voice_agent_hash", sa.String(64)))
    op.execute(
        "UPDATE billing_plans SET limits = COALESCE(limits, '{}'::jsonb) || '{\"voice_minutes_per_month\": 30}'::jsonb"
        " WHERE code = 'individual_voz'"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("server_ai_settings")}
    for column in ("voice_agent_hash", "voice_agents"):
        if column in columns:
            op.drop_column("server_ai_settings", column)
    if "voice_sessions" in inspector.get_table_names():
        op.drop_index("ix_voice_sessions_user_created", table_name="voice_sessions")
        op.drop_table("voice_sessions")
