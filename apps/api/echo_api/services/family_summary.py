"""Resumen de IA de una familia, a partir de los resúmenes y actas de sus reuniones.

Cada persona ve un resumen armado solo con reuniones que puede ver: se guarda
uno por conjunto de reuniones (FamilySummary.meetings_key) y a cada una se le
muestra el más completo de los que no usan reuniones ajenas. Si después hubo
reuniones nuevas, el resumen queda "viejo" y la página lo regenera.
"""
import hashlib
import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ActionItem,
    Decision,
    Family,
    FamilyMember,
    FamilySummary,
    Meeting,
    MeetingReason,
    MeetingSummary,
    Minutes,
    MinutesVersion,
)
from .access import Scope, meeting_filter

log = logging.getLogger("echo.family_summary")

# Las reuniones más recientes que entran al resumen, y cuánto texto de cada cosa.
MAX_MEETINGS = 30
MAX_ACTA_CHARS = 1800
MAX_TOTAL_CHARS = 40_000
# Resúmenes guardados por familia (uno por cada conjunto de reuniones que se vio).
KEEP_PER_FAMILY = 6

SYSTEM = """Sos el equipo de orientación de un colegio y escribís el resumen de la familia para quien la sigue.
Te paso, en orden de fecha, las reuniones que el colegio tuvo con la familia: resumen, decisiones, tareas y un extracto del acta.
Escribí en español rioplatense, claro y sin adornos, como una nota interna. No inventes nada que no esté en las reuniones.
Devolvé un objeto JSON con:
- "overview": 2 a 4 oraciones con la situación de la familia hoy (quiénes, por qué se reúnen, cómo viene).
- "working_on": lista de lo que se viene trabajando con la familia o con el alumno (máximo 6).
- "agreements": lista de acuerdos tomados que siguen vigentes, con la fecha de la reunión entre paréntesis (máximo 8).
- "pending": lista de pendientes o tareas abiertas, con quién se encarga si se sabe (máximo 8).
- "alerts": lista corta de señales que piden atención (faltas reiteradas, gravedad en rojo, temas que se repiten). Vacía si no hay.
Cada punto, una oración corta."""


def meetings_key(ids: list[uuid.UUID] | set[uuid.UUID]) -> str:
    return hashlib.sha256(",".join(sorted(str(i) for i in ids)).encode()).hexdigest()


async def visible_family_meetings(db: AsyncSession, scope: Scope, family_id: uuid.UUID) -> list[Meeting]:
    return list(
        (
            await db.execute(
                select(Meeting)
                .where(
                    Meeting.organization_id == scope.org_id,
                    Meeting.family_id == family_id,
                    Meeting.deleted_at.is_(None),
                    meeting_filter(scope),
                )
                .order_by(func.coalesce(Meeting.started_at, Meeting.created_at))
            )
        ).scalars()
    )


async def _with_content(db: AsyncSession, meetings: list[Meeting]) -> tuple[list[Meeting], datetime | None]:
    """Las reuniones que tienen algo para resumir (resumen o acta) y cuándo cambió eso por última vez."""
    ids = [m.id for m in meetings]
    if not ids:
        return [], None
    summary_rows = (
        await db.execute(
            select(MeetingSummary.meeting_id, func.max(MeetingSummary.updated_at))
            .where(MeetingSummary.meeting_id.in_(ids), MeetingSummary.kind == "executive")
            .group_by(MeetingSummary.meeting_id)
        )
    ).all()
    acta_rows = (
        await db.execute(
            select(Minutes.meeting_id, func.max(MinutesVersion.created_at))
            .join(MinutesVersion, MinutesVersion.minutes_id == Minutes.id)
            .where(Minutes.meeting_id.in_(ids))
            .group_by(Minutes.meeting_id)
        )
    ).all()
    task_changed = (
        await db.execute(select(func.max(ActionItem.updated_at)).where(ActionItem.meeting_id.in_(ids)))
    ).scalar()
    useful = {meeting_id for meeting_id, _ in summary_rows} | {meeting_id for meeting_id, _ in acta_rows}
    moments = [at for _, at in summary_rows + acta_rows if at] + ([task_changed] if task_changed else [])
    return [m for m in meetings if m.id in useful], max(moments) if moments else None


async def summary_state(db: AsyncSession, scope: Scope, family: Family) -> dict:
    """Qué resumen le toca a quien mira y si está al día."""
    meetings, source_at = await _with_content(db, await visible_family_meetings(db, scope, family.id))
    visible = {str(m.id) for m in meetings}
    state = {
        "status": "empty",
        "summary": None,
        "generated_at": None,
        "meetings_used": 0,
        "meetings_available": len(visible),
        "new_meetings": 0,
    }
    if not visible:
        return state
    rows = (
        await db.execute(select(FamilySummary).where(FamilySummary.family_id == family.id))
    ).scalars().all()
    candidates = [row for row in rows if set(row.meeting_ids) <= visible]
    if not candidates:
        return {**state, "status": "none"}
    best = max(candidates, key=lambda row: (len(row.meeting_ids), row.updated_at))
    used = set(best.meeting_ids)
    status = "fresh"
    if used != visible:
        status = "stale"  # hubo reuniones nuevas
    elif source_at and best.source_at and source_at > best.source_at:
        status = "outdated"  # mismas reuniones, pero cambió un resumen, un acta o una tarea
    return {
        **state,
        "status": status,
        "summary": best.content,
        "generated_at": best.updated_at,
        "meetings_used": len(used),
        "new_meetings": len(visible - used),
    }


async def _material(db: AsyncSession, family: Family, meetings: list[Meeting]) -> str:
    """El texto que se le pasa al modelo: una ficha por reunión, de la más vieja a la más nueva."""
    meetings = meetings[-MAX_MEETINGS:]
    ids = [m.id for m in meetings]
    members = (
        (await db.execute(select(FamilyMember).where(FamilyMember.family_id == family.id))).scalars().all()
    )
    by_id = {str(m.id): m for m in members}
    reasons = dict(
        (
            await db.execute(
                select(MeetingReason.id, MeetingReason.name).where(
                    MeetingReason.id.in_({m.reason_id for m in meetings if m.reason_id})
                )
            )
        ).all()
    )
    summaries = {
        row.meeting_id: row.content
        for row in (
            await db.execute(
                select(MeetingSummary).where(MeetingSummary.meeting_id.in_(ids), MeetingSummary.kind == "executive")
            )
        ).scalars()
    }
    actas = dict(
        (
            await db.execute(
                select(Minutes.meeting_id, MinutesVersion.body_markdown)
                .join(
                    MinutesVersion,
                    (MinutesVersion.minutes_id == Minutes.id) & (MinutesVersion.version == Minutes.current_version),
                )
                .where(Minutes.meeting_id.in_(ids))
            )
        ).all()
    )
    decisions: dict[uuid.UUID, list[str]] = {}
    for meeting_id, text in (
        await db.execute(
            select(Decision.meeting_id, Decision.text).where(Decision.meeting_id.in_(ids), Decision.status == "active")
        )
    ).all():
        decisions.setdefault(meeting_id, []).append(text)
    tasks: dict[uuid.UUID, list[str]] = {}
    for task in (
        await db.execute(
            select(ActionItem).where(
                ActionItem.meeting_id.in_(ids), ActionItem.status.in_(("pending", "in_progress", "done"))
            )
        )
    ).scalars():
        who = task.assignee_name or task.suggested_assignee
        state = "hecha" if task.status == "done" else "abierta"
        tasks.setdefault(task.meeting_id, []).append(
            f"{task.text}{f' — {who}' if who else ''}{f' (vence {task.due_date:%d/%m})' if task.due_date else ''} [{state}]"
        )

    children = [m for m in members if m.relationship_type == "estudiante"]
    header = [f"FAMILIA: {family.name}"]
    if children:
        header.append(
            "Hijos: "
            + "; ".join(f"{c.name}{f' ({c.curso})' if c.curso else ''}{f' — {c.level}' if c.level else ''}" for c in children)
        )
    guardians = [m for m in members if m.is_guardian]
    if guardians:
        header.append("Responsables: " + "; ".join(f"{g.name} ({g.relationship_type})" for g in guardians))
    if family.notes:
        header.append(f"Notas de la familia: {family.notes[:600]}")

    blocks: list[str] = []
    total = 0
    # De la más nueva a la más vieja hasta llenar el cupo; después se dan vuelta.
    for meeting in reversed(meetings):
        moment = meeting.started_at or meeting.created_at
        title = [f"### {moment:%d/%m/%Y} — {meeting.title}"]
        if meeting.reason_id and meeting.reason_id in reasons:
            title.append(f"Motivo: {reasons[meeting.reason_id]}")
        if meeting.severity:
            title.append(f"Gravedad: {meeting.severity}")
        students = [by_id[s] for s in meeting.student_ids or [] if s in by_id]
        if students:
            title.append("De: " + ", ".join(s.name for s in students))
        lines = [" · ".join(title)]
        points = (summaries.get(meeting.id) or {}).get("points") or []
        if points:
            lines.append("Resumen:\n" + "\n".join(f"- {p}" for p in points[:8]))
        if decisions.get(meeting.id):
            lines.append("Decisiones:\n" + "\n".join(f"- {d}" for d in decisions[meeting.id][:8]))
        if tasks.get(meeting.id):
            lines.append("Tareas:\n" + "\n".join(f"- {t}" for t in tasks[meeting.id][:10]))
        acta = (actas.get(meeting.id) or "").strip()
        if acta:
            lines.append("Acta (extracto):\n" + acta[:MAX_ACTA_CHARS])
        block = "\n".join(lines)
        if blocks and total + len(block) > MAX_TOTAL_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(header) + "\n\nREUNIONES:\n\n" + "\n\n".join(reversed(blocks))


def _clean(result: dict | list) -> dict:
    if not isinstance(result, dict):
        result = {}

    def items(key: str, limit: int) -> list[str]:
        value = result.get(key) or []
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()][:limit]

    return {
        "overview": str(result.get("overview") or "").strip(),
        "working_on": items("working_on", 6),
        "agreements": items("agreements", 8),
        "pending": items("pending", 8),
        "alerts": items("alerts", 5),
    }


async def generate(db: AsyncSession, scope: Scope, family: Family, provider, model_name: str | None) -> bool:
    """Arma y guarda el resumen con lo que ve `scope`. False = no había nada para resumir."""
    meetings, source_at = await _with_content(db, await visible_family_meetings(db, scope, family.id))
    if not meetings:
        return False
    material = await _material(db, family, meetings)
    content = _clean(
        await provider.chat_json(SYSTEM, [{"role": "user", "content": material}], temperature=0.2, max_tokens=2500)
    )
    ids = sorted(str(m.id) for m in meetings)
    values = {
        "id": uuid.uuid4(),
        "family_id": family.id,
        "organization_id": family.organization_id,
        "meetings_key": meetings_key(ids),
        "meeting_ids": ids,
        "content": content,
        "source_at": source_at,
        "model_used": model_name,
        "created_by": scope.user_id,
    }
    # Dos pestañas generando a la vez el mismo resumen: gana la última.
    statement = insert(FamilySummary).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_family_summary_meetings",
            set_={
                "content": statement.excluded.content,
                "source_at": statement.excluded.source_at,
                "model_used": statement.excluded.model_used,
                "created_by": statement.excluded.created_by,
                "updated_at": func.now(),
            },
        )
    )
    old = (
        select(FamilySummary.id)
        .where(FamilySummary.family_id == family.id)
        .order_by(FamilySummary.updated_at.desc())
        .offset(KEEP_PER_FAMILY)
    )
    await db.execute(delete(FamilySummary).where(FamilySummary.id.in_(old)))
    await db.commit()
    return True
