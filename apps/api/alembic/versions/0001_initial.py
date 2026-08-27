"""Schema inicial de Echo.

Crea la extensión pgvector, todas las tablas del modelo y el trigger
de full-text search sobre transcript_segments.

Revision ID: 0001
Revises:
Create Date: 2026-08-27
"""
from alembic import op

from echo_api.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # Full-text search en español sobre el transcript
    op.execute(
        """
        CREATE OR REPLACE FUNCTION transcript_segments_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.tsv := to_tsvector('spanish', coalesce(NEW.text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transcript_segments_tsv
        BEFORE INSERT OR UPDATE OF text ON transcript_segments
        FOR EACH ROW EXECUTE FUNCTION transcript_segments_tsv_update();
        """
    )

    # Índice vectorial (HNSW) para búsqueda semántica
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_segments_embedding ON transcript_segments "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_entities_embedding ON memory_entities "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_transcript_segments_tsv ON transcript_segments")
    op.execute("DROP FUNCTION IF EXISTS transcript_segments_tsv_update")
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
