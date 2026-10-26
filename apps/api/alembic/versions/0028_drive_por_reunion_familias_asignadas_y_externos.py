"""Drive con una carpeta por familia y otra por reunión; personas asignadas a
cada familia (ven todas sus reuniones); y tareas para gente de afuera de Echo,
que entra con un link que le llega por mail.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "drive_folder_id" not in _columns("meetings"):
        op.add_column("meetings", sa.Column("drive_folder_id", sa.String(120)))
    if "drive_folder_id" not in _columns("families"):
        op.add_column("families", sa.Column("drive_folder_id", sa.String(120)))
    if "drive_file_id" not in _columns("minutes"):
        op.add_column("minutes", sa.Column("drive_file_id", sa.String(120)))
    if "assignee_email" not in _columns("action_items"):
        op.add_column("action_items", sa.Column("assignee_email", sa.String(320)))

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "family_assignments" not in tables:
        op.create_table(
            "family_assignments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("family_id", "user_id", name="uq_family_assignment"),
        )
        op.create_index("ix_family_assignments_org_user", "family_assignments", ["organization_id", "user_id"])
    if "external_access" not in tables:
        op.create_table(
            "external_access",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE")),
            sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("action_items.id", ondelete="CASCADE")),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("name", sa.String(200)),
            sa.Column("scope", sa.String(20), nullable=False, server_default="task"),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("last_seen_at", sa.DateTime(timezone=True)),
            sa.Column("mail_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_external_access_task", "external_access", ["task_id"])
        op.create_index("ix_external_access_meeting", "external_access", ["meeting_id"])


def downgrade() -> None:
    op.drop_table("external_access")
    op.drop_table("family_assignments")
    op.drop_column("action_items", "assignee_email")
    op.drop_column("minutes", "drive_file_id")
    op.drop_column("families", "drive_folder_id")
    op.drop_column("meetings", "drive_folder_id")
