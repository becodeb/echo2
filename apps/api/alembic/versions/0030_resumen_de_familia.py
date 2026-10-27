"""Resumen de IA de cada familia.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("family_summaries"):
        return
    op.create_table(
        "family_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("meetings_key", sa.String(64), nullable=False),
        sa.Column("meeting_ids", JSONB, nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("source_at", sa.DateTime(timezone=True)),
        sa.Column("model_used", sa.String(120)),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("family_id", "meetings_key", name="uq_family_summary_meetings"),
    )
    op.create_index("ix_family_summaries_family", "family_summaries", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_family_summaries_family", table_name="family_summaries")
    op.drop_table("family_summaries")
