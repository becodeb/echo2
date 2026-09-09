"""Superadmin de la instalación y estado del generador de actas.

- users.is_superadmin: ve todas las organizaciones y les configura la IA.
- minutes.generation_status / generation_error / generation_started_at: hasta
  ahora una generación que fallaba no dejaba rastro en ningún lado y la UI se
  quedaba en "generando" para siempre.

Igual que 0002, esta migración inspecciona la base antes de tocar nada: 0001
crea el schema con Base.metadata.create_all(), o sea desde los modelos, así
que en una base nueva estas columnas ya existen y un add_column a secas
explotaría con "column already exists".

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _add_missing(table: str, columns: dict[str, sa.Column]) -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    for name, column in columns.items():
        if name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    _add_missing(
        "users",
        {
            "is_superadmin": sa.Column(
                "is_superadmin", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        },
    )
    _add_missing(
        "minutes",
        {
            "generation_status": sa.Column(
                "generation_status", sa.String(20), nullable=False, server_default="idle"
            ),
            "generation_error": sa.Column("generation_error", sa.String(400), nullable=True),
            "generation_started_at": sa.Column(
                "generation_started_at", sa.DateTime(timezone=True), nullable=True
            ),
        },
    )


def downgrade() -> None:
    op.drop_column("minutes", "generation_started_at")
    op.drop_column("minutes", "generation_error")
    op.drop_column("minutes", "generation_status")
    op.drop_column("users", "is_superadmin")
