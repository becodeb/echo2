"""Default de IA de la instalación, editable por el superadmin.

Existe para que cambiar la key o el modelo del default no dependa de un
redeploy ni de tocar variables de entorno.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "server_ai_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "server_ai_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("llm_provider", sa.String(40), nullable=True),
        sa.Column("llm_model", sa.String(120), nullable=True),
        sa.Column("llm_api_key_enc", sa.Text(), nullable=True),
        sa.Column("llm_base_url", sa.String(300), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("server_ai_settings")
