"""Reportes por organización: familias, motivos, gravedad y asistencia.

Nota de implementación: se traen las reuniones del período y se agrega en
Python en vez de resolver todo con GROUP BYs. Es a propósito. El volumen acá
es institucional (cientos, a lo sumo miles de reuniones por año), y la
pregunta de asistencia — "¿vinieron TODOS los tutores de esta familia?" — en
SQL puro sale ilegible. Si algún día una organización llega a decenas de miles
de reuniones, esto se reescribe con agregados; hoy no paga la complejidad.
"""
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import Family, FamilyMember, Meeting, MeetingAttendance, MeetingReason

router = APIRouter(prefix="/api/reports", tags=["reports"])

SEVERITY_ORDER = ["rojo", "amarillo", "verde"]


class ReportOut(BaseModel):
    range_from: date
    range_to: date
    totals: dict
    by_family: list[dict]
    by_reason: list[dict]
    by_severity: dict
    attendance: dict
    timeline: list[dict]


def _meeting_date(meeting: Meeting) -> datetime:
    return meeting.started_at or meeting.created_at


@router.get("/overview", response_model=ReportOut)
async def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(UTC).date()
    range_to = date_to or today
    # Por defecto, los últimos doce meses: es el período que hace que la
    # serie temporal diga algo.
    range_from = date_from or (range_to - timedelta(days=365))

    start = datetime.combine(range_from, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(range_to, datetime.max.time(), tzinfo=UTC)

    meetings = (
        (
            await db.execute(
                select(Meeting).where(
                    Meeting.organization_id == ctx.org_id,
                    Meeting.deleted_at.is_(None),
                    or_(
                        Meeting.started_at.between(start, end),
                        (Meeting.started_at.is_(None)) & (Meeting.created_at.between(start, end)),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    families = {
        f.id: f
        for f in (
            await db.execute(select(Family).where(Family.organization_id == ctx.org_id))
        )
        .scalars()
        .all()
    }
    reasons = {
        r.id: r
        for r in (
            await db.execute(select(MeetingReason).where(MeetingReason.organization_id == ctx.org_id))
        )
        .scalars()
        .all()
    }
    members = (
        (
            await db.execute(
                select(FamilyMember).where(FamilyMember.family_id.in_(list(families) or [None]))
            )
        )
        .scalars()
        .all()
    )
    members_by_family: dict[uuid.UUID, list[FamilyMember]] = defaultdict(list)
    member_by_id: dict[uuid.UUID, FamilyMember] = {}
    for member in members:
        members_by_family[member.family_id].append(member)
        member_by_id[member.id] = member

    meeting_ids = [m.id for m in meetings]
    attendance_rows = (
        (
            await db.execute(
                select(MeetingAttendance).where(
                    MeetingAttendance.meeting_id.in_(meeting_ids or [None])
                )
            )
        )
        .scalars()
        .all()
    )
    attendance_by_meeting: dict[uuid.UUID, dict[uuid.UUID, bool]] = defaultdict(dict)
    for row in attendance_rows:
        attendance_by_meeting[row.meeting_id][row.family_member_id] = row.attended

    # ── Agregados ────────────────────────────────────────────────
    by_family: dict[uuid.UUID, dict] = {}
    by_reason: dict[uuid.UUID | None, int] = defaultdict(int)
    by_severity: dict[str, int] = {"verde": 0, "amarillo": 0, "rojo": 0, "sin_clasificar": 0}
    timeline: dict[str, dict] = {}
    complete = incomplete = unknown = 0
    missed_by_member: dict[uuid.UUID, int] = defaultdict(int)

    for meeting in meetings:
        moment = _meeting_date(meeting)

        by_severity[meeting.severity if meeting.severity in by_severity else "sin_clasificar"] += 1
        by_reason[meeting.reason_id] += 1

        month = moment.strftime("%Y-%m")
        bucket = timeline.setdefault(
            month, {"month": month, "meetings": 0, "verde": 0, "amarillo": 0, "rojo": 0}
        )
        bucket["meetings"] += 1
        if meeting.severity in ("verde", "amarillo", "rojo"):
            bucket[meeting.severity] += 1

        if meeting.family_id and meeting.family_id in families:
            entry = by_family.setdefault(
                meeting.family_id,
                {
                    "family_id": str(meeting.family_id),
                    "name": families[meeting.family_id].name,
                    "reference": families[meeting.family_id].reference,
                    "meetings": 0,
                    "last_meeting_at": None,
                    "verde": 0,
                    "amarillo": 0,
                    "rojo": 0,
                },
            )
            entry["meetings"] += 1
            if meeting.severity in ("verde", "amarillo", "rojo"):
                entry[meeting.severity] += 1
            previous = entry["last_meeting_at"]
            if previous is None or moment.isoformat() > previous:
                entry["last_meeting_at"] = moment.isoformat()

            guardians = [m for m in members_by_family.get(meeting.family_id, []) if m.is_guardian]
            recorded = attendance_by_meeting.get(meeting.id, {})
            if not guardians or not any(g.id in recorded for g in guardians):
                unknown += 1
            elif all(recorded.get(g.id, False) for g in guardians):
                complete += 1
            else:
                incomplete += 1
                for guardian in guardians:
                    if guardian.id in recorded and not recorded[guardian.id]:
                        missed_by_member[guardian.id] += 1

    absentees = sorted(
        (
            {
                "member_id": str(member_id),
                "name": member_by_id[member_id].name,
                "family": families[member_by_id[member_id].family_id].name
                if member_by_id[member_id].family_id in families
                else None,
                "missed": count,
            }
            for member_id, count in missed_by_member.items()
            if member_id in member_by_id
        ),
        key=lambda item: item["missed"],
        reverse=True,
    )[:10]

    reason_rows = sorted(
        (
            {
                "reason_id": str(reason_id) if reason_id else None,
                "name": reasons[reason_id].name if reason_id in reasons else "Sin motivo",
                "meetings": count,
            }
            for reason_id, count in by_reason.items()
        ),
        key=lambda item: item["meetings"],
        reverse=True,
    )

    family_rows = sorted(by_family.values(), key=lambda item: item["meetings"], reverse=True)

    classified = sum(1 for m in meetings if m.family_id and m.reason_id and m.severity)

    return ReportOut(
        range_from=range_from,
        range_to=range_to,
        totals={
            "meetings": len(meetings),
            "families_with_meetings": len(by_family),
            "classified": classified,
            "unclassified": len(meetings) - classified,
        },
        by_family=family_rows,
        by_reason=reason_rows,
        by_severity=by_severity,
        attendance={
            "complete": complete,
            "incomplete": incomplete,
            "unknown": unknown,
            "absentees": absentees,
        },
        timeline=[timeline[key] for key in sorted(timeline)],
    )
