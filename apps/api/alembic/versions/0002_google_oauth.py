"""Login con Google.

Agrega users.google_sub y vuelve opcional users.password_hash: una cuenta
creada con Google no tiene contraseña hasta que el usuario defina una.

Ojo con esta migración: 0001 no crea el schema con DDL fijo, hace
Base.metadata.create_all(), o sea lo genera desde los modelos tal como estén
en ese momento. Entonces en una base nueva 0001 ya deja users.google_sub
creado y password_hash nullable, y un add_column a secas explota con
"column already exists". Por eso acá se inspecciona la base y se aplica solo
lo que falte: sobre una base vieja hace el cambio, sobre una nueva es un
no-op. Toda migración que toque tablas ya modeladas necesita el mismo
cuidado mientras 0001 siga siendo un create_all.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}

    if "google_sub" not in columns:
        op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))

    if "ix_users_google_sub" not in indexes:
        op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    if not columns.get("password_hash", {}).get("nullable", True):
        op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
