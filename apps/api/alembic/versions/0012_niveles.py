"""Niveles: nivel por reunión y acceso de cada persona por nivel.

Todas las reuniones que ya existen quedan en primaria, y los miembros que ya
estaban quedan con acceso total a primaria: así nadie deja de ver de golpe lo
que veía ayer. Dirección lo ajusta después.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 0001 hace create_all con los modelos actuales: en una base nueva la
    # columna, el índice y la tabla ya existen cuando llega esta migración.
    if "level" not in {column["name"] for column in inspector.get_columns("meetings")}:
        op.add_column("meetings", sa.Column("level", sa.String(20), nullable=True))
    if "ix_meetings_org_level" not in {index["name"] for index in inspector.get_indexes("meetings")}:
        op.create_index("ix_meetings_org_level", "meetings", ["organization_id", "level"])

    if "member_level_access" not in set(inspector.get_table_names()):
        op.create_table(
            "member_level_access",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("level", sa.String(20), nullable=False),
            sa.Column("access", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "user_id", "level", name="uq_member_level_access"),
        )
        op.create_index(
            "ix_member_level_access_org_user", "member_level_access", ["organization_id", "user_id"]
        )

    op.execute("UPDATE meetings SET level = 'primaria' WHERE level IS NULL")
    # Admins y owners ven todo por su rol: no necesitan fila.
    op.execute(
        """
        INSERT INTO member_level_access (id, organization_id, user_id, level, access)
        SELECT gen_random_uuid(), m.organization_id, m.user_id, 'primaria', 'total'
        FROM organization_members m
        WHERE m.role NOT IN ('admin', 'owner')
        ON CONFLICT ON CONSTRAINT uq_member_level_access DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_member_level_access_org_user", table_name="member_level_access")
    op.drop_table("member_level_access")
    op.drop_index("ix_meetings_org_level", table_name="meetings")
    op.drop_column("meetings", "level")
