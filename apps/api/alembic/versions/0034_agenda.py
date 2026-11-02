"""Agenda: reuniones agendadas para un día, con todo cargado.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "scheduled_meetings" in sa.inspect(op.get_bind()).get_table_names():
        return
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "scheduled_meetings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.String(5)),
        sa.Column("kind", sa.String(20), server_default="familia", nullable=False),
        sa.Column("title", sa.String(300), server_default="", nullable=False),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="SET NULL")),
        sa.Column("student_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("reason_id", uuid, sa.ForeignKey("meeting_reasons.id", ondelete="SET NULL")),
        sa.Column("level", sa.String(20)),
        sa.Column("group_id", uuid, sa.ForeignKey("internal_groups.id", ondelete="SET NULL")),
        sa.Column("staff_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="agendada", nullable=False),
        sa.Column("meeting_id", uuid, sa.ForeignKey("meetings.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_scheduled_meetings_org_date", "scheduled_meetings", ["organization_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_meetings_org_date", table_name="scheduled_meetings")
    op.drop_table("scheduled_meetings")
