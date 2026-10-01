"""Huella de voz: nombres por "Mi voz" (docs/plan-correcciones.md §7.2 y §7.4).

- user_voice_samples: la huella de la muestra (sample_embedding), el perfil
  que se usa para comparar (embedding: la muestra, más lo aprendido de las
  reuniones si la persona lo permite), con qué modelo se calculó, cuántas
  reuniones sumó y si puede aprender (learn_from_meetings).
- speakers: a qué usuario quedó vinculada la persona y cómo se supo su
  nombre (name_source: voz | dijo | ia | manual).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    samples = _columns("user_voice_samples")
    if "sample_embedding" not in samples:
        op.add_column("user_voice_samples", sa.Column("sample_embedding", Vector(256)))
    if "embedding" not in samples:
        op.add_column("user_voice_samples", sa.Column("embedding", Vector(256)))
    if "embedding_model" not in samples:
        op.add_column("user_voice_samples", sa.Column("embedding_model", sa.String(60)))
    if "learned_count" not in samples:
        op.add_column("user_voice_samples", sa.Column("learned_count", sa.Integer(), nullable=False, server_default="0"))
    if "learn_from_meetings" not in samples:
        op.add_column(
            "user_voice_samples",
            sa.Column("learn_from_meetings", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    speakers = _columns("speakers")
    if "user_id" not in speakers:
        op.add_column(
            "speakers",
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        )
    if "name_source" not in speakers:
        op.add_column("speakers", sa.Column("name_source", sa.String(20)))


def downgrade() -> None:
    speakers = _columns("speakers")
    for column in ("name_source", "user_id"):
        if column in speakers:
            op.drop_column("speakers", column)
    samples = _columns("user_voice_samples")
    for column in ("learn_from_meetings", "learned_count", "embedding_model", "embedding", "sample_embedding"):
        if column in samples:
            op.drop_column("user_voice_samples", column)
