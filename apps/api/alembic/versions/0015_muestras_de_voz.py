"""Muestras de voz para reconocer a cada persona por nombre en las reuniones.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 hace create_all con los modelos actuales: en una base nueva ya existe.
    if "user_voice_samples" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "user_voice_samples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_wav", sa.LargeBinary, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_user_voice_sample"),
    )


def downgrade() -> None:
    op.drop_table("user_voice_samples")
