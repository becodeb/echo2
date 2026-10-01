"""Foto de perfil: users.avatar_url (la de Google, se refresca en cada login).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "avatar_url" not in columns:
        op.add_column("users", sa.Column("avatar_url", sa.String(600)))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "avatar_url" in columns:
        op.drop_column("users", "avatar_url")
