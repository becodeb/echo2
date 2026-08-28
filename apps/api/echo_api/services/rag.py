"""RAG: embeddings del transcript + retrieval semántico con pgvector."""
import logging
import re
import uuid

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models import Meeting, Speaker, TranscriptSegment
from .ai_settings import EmbeddingsConfig
from .embeddings import embed_texts

log = logging.getLogger("echo.rag")

EMBED_BATCH = 64
# los segmentos cortos se agrupan en chunks de ~600 chars para mejor recall
CHUNK_TARGET_CHARS = 600


async def embed_meeting_segments(meeting_id: uuid.UUID, config: EmbeddingsConfig) -> int:
    """Genera embeddings para los segmentos finales sin embedding."""
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(TranscriptSegment)
                    .where(
                        TranscriptSegment.meeting_id == meeting_id,
                        TranscriptSegment.is_final.is_(True),
                        TranscriptSegment.embedding.is_(None),
                    )
                    .order_by(TranscriptSegment.seq)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        total = 0
        for start in range(0, len(rows), EMBED_BATCH):
            batch = rows[start : start + EMBED_BATCH]
            vectors = await embed_texts(config, [segment.text for segment in batch])
            for segment, vector in zip(batch, vectors):
                segment.embedding = vector
            total += len(batch)
            await db.commit()
        return total


async def semantic_search_segments(
    db: AsyncSession,
    org_id: uuid.UUID,
    query_vector: list[float],
    limit: int = 12,
    meeting_id: uuid.UUID | None = None,
) -> list[dict]:
    """Búsqueda por similitud coseno, SIEMPRE aislada por organización."""
    vector_literal = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
    filters = "s.organization_id = :org_id AND s.embedding IS NOT NULL"
    params: dict = {"org_id": str(org_id), "limit": limit}
    if meeting_id:
        filters += " AND s.meeting_id = :meeting_id"
        params["meeting_id"] = str(meeting_id)
    query = sql_text(
        f"""
        SELECT s.id, s.meeting_id, s.seq, s.start_ms, s.end_ms, s.text, s.speaker_id,
               1 - (s.embedding <=> '{vector_literal}'::vector) AS similarity
        FROM transcript_segments s
        WHERE {filters}
        ORDER BY s.embedding <=> '{vector_literal}'::vector
        LIMIT :limit
        """
    )
    rows = (await db.execute(query, params)).all()
    if not rows:
        return []

    speaker_ids = {row.speaker_id for row in rows if row.speaker_id}
    speakers = {}
    if speaker_ids:
        for speaker in (
            (await db.execute(select(Speaker).where(Speaker.id.in_(speaker_ids)))).scalars().all()
        ):
            speakers[speaker.id] = speaker.display_name or speaker.label

    meeting_ids = {row.meeting_id for row in rows}
    meetings = {}
    for meeting in (
        (await db.execute(select(Meeting).where(Meeting.id.in_(meeting_ids)))).scalars().all()
    ):
        meetings[meeting.id] = meeting

    results = []
    for row in rows:
        meeting = meetings.get(row.meeting_id)
        results.append(
            {
                "segment_id": str(row.id),
                "meeting_id": str(row.meeting_id),
                "meeting_title": meeting.title if meeting else "",
                "meeting_date": meeting.started_at.isoformat() if meeting and meeting.started_at else None,
                "seq": row.seq,
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "speaker": speakers.get(row.speaker_id),
                "text": row.text,
                "similarity": float(row.similarity),
            }
        )
    return results


_TSQUERY_SPLIT = re.compile(r"[^0-9a-záéíóúüñ]+", re.IGNORECASE)


def build_or_tsquery(question: str) -> str:
    """Arma un tsquery con OR entre los términos de la pregunta.

    plainto_tsquery une TODOS los lexemas con AND, así que una pregunta en
    lenguaje natural ("¿qué se dijo sobre el presupuesto?") exige un segmento
    que contenga "dijo" Y "presupuesto" juntos y no devuelve nada. Con OR el
    ranking (ts_rank) decide la relevancia en vez de exigir coincidencia total.

    Las stopwords las descarta el diccionario 'spanish' de Postgres.
    """
    tokens = [token for token in _TSQUERY_SPLIT.split(question.lower()) if len(token) > 1]
    return " | ".join(tokens)


async def keyword_search_segments(
    db: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    limit: int = 12,
    meeting_id: uuid.UUID | None = None,
) -> list[dict]:
    """Full-text search (fallback sin embeddings y complemento del semántico)."""
    tsquery = build_or_tsquery(query)
    if not tsquery:
        return []
    filters = "s.organization_id = :org_id AND s.tsv @@ to_tsquery('spanish', :q)"
    params: dict = {"org_id": str(org_id), "q": tsquery, "limit": limit}
    if meeting_id:
        filters += " AND s.meeting_id = :meeting_id"
        params["meeting_id"] = str(meeting_id)
    sql = sql_text(
        f"""
        SELECT s.id, s.meeting_id, s.seq, s.start_ms, s.end_ms, s.text, s.speaker_id,
               ts_rank(s.tsv, to_tsquery('spanish', :q)) AS rank
        FROM transcript_segments s
        WHERE {filters}
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    rows = (await db.execute(sql, params)).all()
    meeting_ids = {row.meeting_id for row in rows}
    meetings = {
        meeting.id: meeting
        for meeting in (
            (await db.execute(select(Meeting).where(Meeting.id.in_(meeting_ids)))).scalars().all()
        )
    }
    return [
        {
            "segment_id": str(row.id),
            "meeting_id": str(row.meeting_id),
            "meeting_title": meetings[row.meeting_id].title if row.meeting_id in meetings else "",
            "meeting_date": meetings[row.meeting_id].started_at.isoformat()
            if row.meeting_id in meetings and meetings[row.meeting_id].started_at
            else None,
            "seq": row.seq,
            "start_ms": row.start_ms,
            "end_ms": row.end_ms,
            "speaker": None,
            "text": row.text,
            "similarity": float(row.rank),
        }
        for row in rows
    ]


async def retrieve_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    question: str,
    embeddings_config: EmbeddingsConfig | None,
    meeting_id: uuid.UUID | None = None,
    limit: int = 12,
) -> list[dict]:
    """Retrieval híbrido: semántico si hay embeddings, keyword siempre."""
    results: list[dict] = []
    seen: set[str] = set()
    if embeddings_config:
        try:
            vectors = await embed_texts(embeddings_config, [question])
            semantic = await semantic_search_segments(
                db, org_id, vectors[0], limit=limit, meeting_id=meeting_id
            )
            for item in semantic:
                if item["segment_id"] not in seen:
                    seen.add(item["segment_id"])
                    results.append(item)
        except Exception as exc:
            log.warning("retrieval semantico fallo, uso keyword: %s", exc)
    keyword = await keyword_search_segments(db, org_id, question, limit=limit, meeting_id=meeting_id)
    for item in keyword:
        if item["segment_id"] not in seen:
            seen.add(item["segment_id"])
            results.append(item)
    return results[: limit + 4]
