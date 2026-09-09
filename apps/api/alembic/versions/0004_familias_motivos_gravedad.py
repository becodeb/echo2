"""Familias, motivos de reunión, gravedad y asistencia.

Igual que 0002 y 0003, inspecciona antes de tocar: 0001 arma el schema con
Base.metadata.create_all(), así que en una base nueva estas tablas y columnas
ya nacen creadas, mientras que en una base que se creó antes de este cambio
hay que crearlas de verdad. Las dos situaciones existen hoy, así que la
migración tiene que servir para ambas.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "families" not in tables:
        op.create_table(
            "families",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("reference", sa.String(80), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_families_org", "families", ["organization_id"])

    if "family_members" not in tables:
        op.create_table(
            "family_members",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "family_id",
                UUID(as_uuid=True),
                sa.ForeignKey("families.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("relationship_type", sa.String(20), nullable=False, server_default="tutor"),
            sa.Column("is_guardian", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("phone", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_family_members_family", "family_members", ["family_id"])

    if "meeting_reasons" not in tables:
        op.create_table(
            "meeting_reasons",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "name", name="uq_meeting_reason_name"),
        )
        op.create_index("ix_meeting_reasons_org", "meeting_reasons", ["organization_id"])

    if "meeting_attendance" not in tables:
        op.create_table(
            "meeting_attendance",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "meeting_id",
                UUID(as_uuid=True),
                sa.ForeignKey("meetings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "family_member_id",
                UUID(as_uuid=True),
                sa.ForeignKey("family_members.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("attended", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("meeting_id", "family_member_id", name="uq_meeting_attendance"),
        )
        op.create_index("ix_meeting_attendance_meeting", "meeting_attendance", ["meeting_id"])
        op.create_index("ix_meeting_attendance_member", "meeting_attendance", ["family_member_id"])

    meeting_columns = _columns("meetings")
    if "family_id" not in meeting_columns:
        op.add_column(
            "meetings",
            sa.Column(
                "family_id",
                UUID(as_uuid=True),
                sa.ForeignKey("families.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "reason_id" not in meeting_columns:
        op.add_column(
            "meetings",
            sa.Column(
                "reason_id",
                UUID(as_uuid=True),
                sa.ForeignKey("meeting_reasons.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "severity" not in meeting_columns:
        op.add_column("meetings", sa.Column("severity", sa.String(10), nullable=True))

    if "ix_meetings_family" not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("meetings")}:
        op.create_index("ix_meetings_family", "meetings", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_meetings_family", table_name="meetings")
    op.drop_column("meetings", "severity")
    op.drop_column("meetings", "reason_id")
    op.drop_column("meetings", "family_id")
    op.drop_table("meeting_attendance")
    op.drop_table("meeting_reasons")
    op.drop_table("family_members")
    op.drop_table("families")
