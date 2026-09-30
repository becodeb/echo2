"""Pedidos de plan ("Suscribirme" / "Contact sales") y aviso de muestra de voz.

- plan_requests: quién pidió qué plan y cuándo. Todavía no hay cobro: el
  pedido queda y se avisa a Becode.
- users.voice_prompt_seen_at: la invitación a grabar la voz se muestra una
  sola vez a quien no tiene muestra.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # 0001 hace create_all con los modelos actuales: en una base nueva ya existe todo.
    if "voice_prompt_seen_at" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("voice_prompt_seen_at", sa.DateTime(timezone=True)))
    if "plan_requests" not in set(inspector.get_table_names()):
        op.create_table(
            "plan_requests",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")
            ),
            sa.Column("plan", sa.String(30), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="new"),
            sa.Column("message", sa.String(1000)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_plan_requests_created", "plan_requests", ["created_at"])


def downgrade() -> None:
    op.drop_table("plan_requests")
    op.drop_column("users", "voice_prompt_seen_at")
