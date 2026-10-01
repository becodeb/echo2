"""Dispositivos: devices.minors ("pueden hablar menores", por defecto sí).

Un Echo Device puede estar en un aula: sus reuniones van sin ElevenLabs ni
voz salvo que un admin lo apague (docs/plan-correcciones.md §1.3).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "minors" not in columns:
        op.add_column("devices", sa.Column("minors", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "minors" in columns:
        op.drop_column("devices", "minors")
