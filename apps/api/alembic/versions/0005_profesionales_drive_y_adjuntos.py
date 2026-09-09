"""Directorio de profesionales, carpeta de Drive por familia y links adjuntos.

Mismo cuidado que 0002/0003/0004: 0001 arma el schema con create_all() desde
los modelos, así que en una base nueva esto ya existe y hay que inspeccionar
antes de crear.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "professionals" not in tables:
        op.create_table(
            "professionals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("role_label", sa.String(120), nullable=True),
            sa.Column("affiliation", sa.String(200), nullable=True),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("phone", sa.String(40), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            *TIMESTAMPS,
        )
        op.create_index("ix_professionals_org", "professionals", ["organization_id"])

    if "family_professionals" not in tables:
        op.create_table(
            "family_professionals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "family_id",
                UUID(as_uuid=True),
                sa.ForeignKey("families.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "professional_id",
                UUID(as_uuid=True),
                sa.ForeignKey("professionals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            *TIMESTAMPS,
            sa.UniqueConstraint("family_id", "professional_id", name="uq_family_professional"),
        )
        op.create_index("ix_family_professionals_family", "family_professionals", ["family_id"])

    if "meeting_professional_attendance" not in tables:
        op.create_table(
            "meeting_professional_attendance",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "meeting_id",
                UUID(as_uuid=True),
                sa.ForeignKey("meetings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "professional_id",
                UUID(as_uuid=True),
                sa.ForeignKey("professionals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("attended", sa.Boolean(), nullable=False, server_default=sa.true()),
            *TIMESTAMPS,
            sa.UniqueConstraint("meeting_id", "professional_id", name="uq_meeting_professional"),
        )
        op.create_index(
            "ix_meeting_professional_meeting", "meeting_professional_attendance", ["meeting_id"]
        )

    if "meeting_attachments" not in tables:
        op.create_table(
            "meeting_attachments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "meeting_id",
                UUID(as_uuid=True),
                sa.ForeignKey("meetings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("url", sa.String(1000), nullable=False),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("added_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            *TIMESTAMPS,
        )
        op.create_index("ix_meeting_attachments_meeting", "meeting_attachments", ["meeting_id"])

    if "drive_url" not in {c["name"] for c in inspector.get_columns("families")}:
        op.add_column("families", sa.Column("drive_url", sa.String(600), nullable=True))

    if "audience" not in {c["name"] for c in inspector.get_columns("meetings")}:
        op.add_column("meetings", sa.Column("audience", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "audience")
    op.drop_column("families", "drive_url")
    op.drop_table("meeting_attachments")
    op.drop_table("meeting_professional_attendance")
    op.drop_table("family_professionals")
    op.drop_table("professionals")
