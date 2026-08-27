"""Exportaciones: acta y transcript en Markdown, TXT, DOCX y PDF."""
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context
from ..models import Minutes, MinutesVersion
from ..services.transcript_util import format_ms, load_transcript_lines

router = APIRouter(prefix="/api/meetings/{meeting_id}/export", tags=["exports"])


async def _get_minutes_markdown(db: AsyncSession, meeting_id: uuid.UUID) -> str:
    minutes = (
        await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
    ).scalar_one_or_none()
    if not minutes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta reunión todavía no tiene acta")
    version = (
        await db.execute(
            select(MinutesVersion).where(
                MinutesVersion.minutes_id == minutes.id,
                MinutesVersion.version == minutes.current_version,
            )
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Acta sin contenido")
    return version.body_markdown


def _markdown_to_docx(markdown: str, title: str) -> bytes:
    from docx import Document

    document = Document()
    document.core_properties.title = title
    table = None
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue  # separador de tabla markdown
            if table is None:
                table = document.add_table(rows=0, cols=len(cells))
                table.style = "Light Grid Accent 1"
            row = table.add_row()
            for index, cell_text in enumerate(cells):
                if index < len(row.cells):
                    row.cells[index].text = cell_text
            continue
        table = None
        if line.startswith("### "):
            document.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            document.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=1)
        elif line.startswith(("- ", "* ")):
            document.add_paragraph(line[2:], style="List Bullet")
        elif line.startswith("> "):
            document.add_paragraph(line[2:], style="Intense Quote")
        elif line.strip() in ("---", "***"):
            document.add_paragraph()
        elif line.strip():
            paragraph = document.add_paragraph()
            _add_runs_with_bold(paragraph, line)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _add_runs_with_bold(paragraph, text: str) -> None:
    parts = text.split("**")
    for index, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run(part)
        run.bold = index % 2 == 1


def _markdown_to_pdf(markdown: str, title: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from xml.sax.saxutils import escape

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, title=title,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("EchoBody", parent=styles["BodyText"], fontSize=10, leading=14)
    elements = []
    table_rows: list[list[str]] = []

    def flush_table():
        nonlocal table_rows
        if table_rows:
            table = Table([[Paragraph(escape(cell), body_style) for cell in row] for row in table_rows])
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            elements.append(table)
            elements.append(Spacer(1, 6))
            table_rows = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            table_rows.append(cells)
            continue
        flush_table()
        content = escape(line).replace("**", "")
        if line.startswith("# "):
            elements.append(Paragraph(escape(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            elements.append(Paragraph(escape(line[3:]), styles["Heading2"]))
        elif line.startswith("### "):
            elements.append(Paragraph(escape(line[4:]), styles["Heading3"]))
        elif line.startswith(("- ", "* ")):
            elements.append(Paragraph("• " + escape(line[2:]).replace("**", ""), body_style))
        elif line.strip() in ("---", "***"):
            elements.append(Spacer(1, 8))
        elif line.strip():
            elements.append(Paragraph(content, body_style))
        else:
            elements.append(Spacer(1, 4))
    flush_table()
    document.build(elements)
    return output.getvalue()


@router.get("/minutes.{fmt}")
async def export_minutes(
    meeting_id: uuid.UUID,
    fmt: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    markdown = await _get_minutes_markdown(db, meeting.id)
    filename = f"acta-{meeting.title[:40].replace(' ', '-')}"

    if fmt == "md":
        return Response(
            markdown, media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )
    if fmt == "txt":
        plain = markdown.replace("#", "").replace("**", "").replace("|", "  ")
        return Response(
            plain, media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.txt"'},
        )
    if fmt == "docx":
        blob = _markdown_to_docx(markdown, meeting.title)
        return Response(
            blob,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'},
        )
    if fmt == "pdf":
        blob = _markdown_to_pdf(markdown, meeting.title)
        return Response(
            blob, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Formato no soportado (md|txt|docx|pdf)")


@router.get("/transcript.{fmt}")
async def export_transcript(
    meeting_id: uuid.UUID,
    fmt: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    lines = await load_transcript_lines(db, meeting.id)
    filename = f"transcript-{meeting.title[:40].replace(' ', '-')}"

    if fmt == "md":
        body = f"# Transcript — {meeting.title}\n\n" + "\n\n".join(
            f"**[{format_ms(l['start_ms'])}] {l['speaker'] or 'Hablante'}:** {l['text']}" for l in lines
        )
        return Response(
            body, media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )
    if fmt == "txt":
        body = "\n".join(
            f"[{format_ms(l['start_ms'])}] {l['speaker'] or 'Hablante'}: {l['text']}" for l in lines
        )
        return Response(
            body, media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.txt"'},
        )
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Formato no soportado (md|txt)")
