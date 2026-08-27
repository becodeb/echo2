"""Utilidades compartidas sobre el transcript."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Speaker, TranscriptSegment


def format_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    total_seconds = int(ms / 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


async def load_transcript_lines(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    start_seq: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Carga el transcript con nombre de hablante resuelto."""
    query = (
        select(TranscriptSegment, Speaker)
        .outerjoin(Speaker, Speaker.id == TranscriptSegment.speaker_id)
        .where(TranscriptSegment.meeting_id == meeting_id, TranscriptSegment.is_final.is_(True))
        .order_by(TranscriptSegment.seq)
    )
    if start_seq is not None:
        query = query.where(TranscriptSegment.seq >= start_seq)
    if limit:
        query = query.limit(limit)
    rows = (await db.execute(query)).all()
    lines = []
    for segment, speaker in rows:
        speaker_name = None
        if speaker:
            speaker_name = speaker.display_name or speaker.label
        lines.append(
            {
                "id": str(segment.id),
                "seq": segment.seq,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "speaker": speaker_name,
                "text": segment.text,
                "confidence": segment.confidence,
            }
        )
    return lines


def transcript_to_text(lines: list[dict], with_timestamps: bool = True) -> str:
    """Render lineal del transcript para prompts y exports."""
    output = []
    for line in lines:
        prefix = ""
        if with_timestamps:
            prefix += f"[{format_ms(line['start_ms'])}] "
        if line.get("speaker"):
            prefix += f"{line['speaker']}: "
        output.append(prefix + line["text"])
    return "\n".join(output)
