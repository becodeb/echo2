"""Número de acta correlativo por organización y motivos por defecto.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-25
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Copia congelada de services/default_reasons.py: la migración no importa
# código de la app, que puede cambiar después.
DEFAULT_REASONS = [
    "Desempeño académico",
    "Conducta",
    "Convivencia escolar",
    "Asistencia e inasistencias",
    "Dificultades de aprendizaje",
    "Aspectos socioemocionales",
    "Vínculo con compañeros",
    "Situación familiar",
    "Salud",
    "Inclusión y acompañamiento (PPI)",
    "Situación de acoso escolar",
    "Devolución de informes",
    "Entrevista de ingreso",
    "Orientación vocacional",
    "Seguimiento",
    "Otro",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 0001 hace create_all con los modelos actuales: en una base nueva las
    # columnas, la tabla y el índice ya existen cuando llega esta migración.
    columns = {column["name"] for column in inspector.get_columns("minutes")}
    if "number" not in columns:
        op.add_column("minutes", sa.Column("number", sa.Integer(), nullable=True))
    if "number_series" not in columns:
        op.add_column("minutes", sa.Column("number_series", sa.String(60), nullable=True))

    if "uq_minutes_number" not in {index["name"] for index in inspector.get_indexes("minutes")}:
        op.create_index(
            "uq_minutes_number",
            "minutes",
            ["organization_id", "number_series", "number"],
            unique=True,
            postgresql_where=sa.text("number IS NOT NULL"),
        )

    if "minutes_counters" not in set(inspector.get_table_names()):
        op.create_table(
            "minutes_counters",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("series", sa.String(60), nullable=False, server_default="general"),
            sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("organization_id", "series", name="uq_minutes_counter_series"),
        )

    # A cada organización se le agregan los motivos por defecto que le falten.
    # Se compara por nombre sin mayúsculas contra todos sus motivos, también
    # los desactivados: uno que el colegio sacó a propósito no reaparece. Los
    # nuevos van al final de la lista, después de los que ya tenía.
    existing: dict = {}
    last_position: dict = {}
    for org_id, name, position in bind.execute(
        sa.text(
            "SELECT o.id, r.name, r.position FROM organizations o "
            "LEFT JOIN meeting_reasons r ON r.organization_id = o.id "
            "WHERE o.deleted_at IS NULL"
        )
    ):
        existing.setdefault(org_id, set())
        last_position.setdefault(org_id, 0)
        if name is not None:
            existing[org_id].add(name.strip().lower())
            last_position[org_id] = max(last_position[org_id], position or 0)

    rows = []
    for org_id, names in existing.items():
        position = last_position[org_id]
        for name in DEFAULT_REASONS:
            if name.lower() in names:
                continue
            position += 1
            rows.append(
                {"id": uuid.uuid4(), "organization_id": org_id, "name": name, "is_active": True, "position": position}
            )

    reasons = sa.table(
        "meeting_reasons",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("organization_id", UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("position", sa.Integer),
    )
    if rows:
        op.bulk_insert(reasons, rows)


def downgrade() -> None:
    # Los motivos quedan: ya pueden estar usados por reuniones.
    op.drop_table("minutes_counters")
    op.drop_index("uq_minutes_number", table_name="minutes")
    op.drop_column("minutes", "number_series")
    op.drop_column("minutes", "number")
