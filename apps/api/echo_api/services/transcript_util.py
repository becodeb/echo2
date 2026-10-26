"""Utilidades compartidas sobre el transcript."""
import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Speaker, TranscriptSegment


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFD", (text or "").lower())
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    # Los marcadores de seudónimos ([PERSONA_3]) no cuentan: el transcript tiene el nombre.
    plain = re.sub(r"\[[^\]]*\]", " ", plain)
    return [word for word in re.findall(r"[a-z0-9]+", plain) if len(word) >= 3]


# Ventana alrededor de la evidencia donde tiene que estar la frase citada.
QUOTE_WINDOW_MS = 120_000


def is_grounded(item: dict, lines: list[dict]) -> bool:
    """La tarea trae una cita ("quote") que de verdad se dijo cerca de su evidencia.

    Las tareas inventadas (26/10: "generó tareas no reales") salían de temas
    de la charla convertidos en pendientes. Sin una frase que lo muestre, no
    hay tarea: alcanza con que el 70% de sus palabras estén en lo que se dijo
    en los dos minutos alrededor.
    """
    quote = _words(str(item.get("quote") or ""))
    if len(quote) < 2:
        return False
    try:
        at = int(item.get("evidence_start_ms")) if item.get("evidence_start_ms") is not None else None
    except (TypeError, ValueError):
        at = None
    window = [
        line for line in lines
        if at is None or abs((line.get("start_ms") or 0) - at) <= QUOTE_WINDOW_MS
    ] or lines
    said = set(_words(" ".join(str(line.get("text") or "") for line in window)))
    return sum(word in said for word in quote) / len(quote) >= 0.7


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
