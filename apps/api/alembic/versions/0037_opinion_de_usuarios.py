"""Opinión de los usuarios: los popups de estrellitas y de sugerencias.

Revision ID: 0037
Revises: 0035
Create Date: 2026-11-05

Con chequeos porque en una base nueva 0001 ya arma las tablas desde los modelos.
Es 0037 y cuelga de 0035 porque 0036 la está usando la rama de Pedidos de cambios:
la que se mergee segunda tiene que colgar de la otra, o alembic queda con dos cabezas.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("feedback_prompts"):
        op.create_table(
            "feedback_prompts",
            sa.Column("kind", sa.String(20), primary_key=True),
            sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("question", sa.String(300), nullable=False),
            sa.Column("every_days", sa.Integer(), server_default="60", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if not inspector.has_table("feedback_responses"):
        op.create_table(
            "feedback_responses",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("stars", sa.Integer()),
            sa.Column("text", sa.Text()),
            sa.Column("dismissed", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("stars IS NULL OR stars BETWEEN 1 AND 5", name="ck_feedback_stars"),
        )
        op.create_index("ix_feedback_user_kind_created", "feedback_responses", ["user_id", "kind", "created_at"])
        op.create_index("ix_feedback_created", "feedback_responses", ["created_at"])


def downgrade() -> None:
    op.drop_table("feedback_responses")
    op.drop_table("feedback_prompts")
