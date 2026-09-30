"""Planes, créditos y consumo.

- organizations.plan / is_personal / limits y users.plan / limits.
- billing_plans: qué incluye cada plan y sus topes, con los valores cerrados
  con Bauti el 30/9 (docs/plan-transcripcion-y-planes.md, §5). Son el punto
  de partida: después los cambia un superadmin desde el panel, sin deploy.
- usage_events: segundos de audio por proveedor, minutos de voz, tokens, en
  dólares, y los créditos que gastó cada reunión.

Ninguna organización queda como "cortesia" (todo habilitado sin pagar) por
esta migración: Northfield se marca desde el panel de superadmin después de
confirmar cuál es en la base.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# (code, name, scope, price_usd, features, limits, sort)
PLANS = [
    ("base", "Gratis", "any", 0, '{"people": "credits", "voice": false}', '{"credits_per_month": 4}', 0),
    ("individual", "Individual", "user", 5, '{"people": "always", "voice": false}', '{"people_hours_per_month": 5}', 1),
    (
        "individual_voz",
        "Individual + voz",
        "user",
        10,
        '{"people": "always", "voice": true}',
        '{"people_hours_per_month": 5, "voice_minutes_per_month": 30}',
        2,
    ),
    ("institucion", "Instituciones", "organization", None, '{"people": "always", "voice": false}', "{}", 3),
    ("cortesia", "Cortesía", "organization", None, '{"people": "always", "voice": false}', "{}", 4),
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    # 0001 hace create_all con los modelos actuales: en una base nueva las
    # columnas y tablas ya existen cuando llega esta migración.
    org_columns = {column["name"] for column in inspector.get_columns("organizations")}
    if "plan" not in org_columns:
        op.add_column("organizations", sa.Column("plan", sa.String(30), server_default="base", nullable=False))
    if "is_personal" not in org_columns:
        op.add_column(
            "organizations", sa.Column("is_personal", sa.Boolean, server_default=sa.false(), nullable=False)
        )
    if "limits" not in org_columns:
        op.add_column("organizations", sa.Column("limits", JSONB))

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "plan" not in user_columns:
        op.add_column("users", sa.Column("plan", sa.String(30), server_default="base", nullable=False))
    if "limits" not in user_columns:
        op.add_column("users", sa.Column("limits", JSONB))

    if "billing_plans" not in tables:
        op.create_table(
            "billing_plans",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("code", sa.String(30), nullable=False, unique=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("scope", sa.String(20), nullable=False),
            sa.Column("price_usd", sa.Numeric(10, 2)),
            sa.Column("features", JSONB, nullable=False, server_default="{}"),
            sa.Column("limits", JSONB, nullable=False, server_default="{}"),
            sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
            *_timestamps(),
        )

    if "usage_events" not in tables:
        op.create_table(
            "usage_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE")
            ),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="SET NULL")),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(120)),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("quantity", sa.Float, nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
            sa.Column("credits", sa.Integer, nullable=False, server_default="0"),
            sa.Column("meta", JSONB),
            *_timestamps(),
        )
        op.create_index("ix_usage_org_created", "usage_events", ["organization_id", "created_at"])
        op.create_index("ix_usage_user_created", "usage_events", ["user_id", "created_at"])
        op.create_index("ix_usage_meeting", "usage_events", ["meeting_id"])

    # Los planes se cargan siempre (también en una base nueva, donde la tabla
    # la creó 0001 vacía). Un plan que ya existe no se toca: lo pudo haber
    # ajustado un superadmin.
    for code, name, scope, price, features, limits, sort in PLANS:
        op.execute(
            sa.text(
                "INSERT INTO billing_plans (id, code, name, scope, price_usd, features, limits, sort, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :code, :name, :scope, :price, CAST(:features AS jsonb), "
                "CAST(:limits AS jsonb), :sort, now(), now()) ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, name=name, scope=scope, price=price, features=features, limits=limits, sort=sort)
        )


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("billing_plans")
    op.drop_column("users", "limits")
    op.drop_column("users", "plan")
    op.drop_column("organizations", "limits")
    op.drop_column("organizations", "is_personal")
    op.drop_column("organizations", "plan")
