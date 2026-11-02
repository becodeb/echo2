"""Agenda: las reuniones que vienen, cargadas de antemano (models/agenda.py).

Cada uno ve lo que agendó, a lo que lo sumaron y lo de sus grupos internos.
Quien ve todo un nivel (o administra la sede) puede pedir "Todo mi nivel".
"""
import datetime as dt
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import (
    LEVELS,
    Family,
    FamilyMember,
    InternalGroup,
    Meeting,
    MeetingReason,
    Minutes,
    ScheduledMeeting,
    User,
)
from ..services.access import Scope
from ..services.audit import audit

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

# Un pedido trae como mucho un poco más de un mes (la grilla del calendario).
MAX_RANGE_DAYS = 45


class ScheduleIn(BaseModel):
    date: dt.date
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    kind: Literal["familia", "interna"] = "familia"
    title: str = Field(default="", max_length=300)
    family_id: uuid.UUID | None = None
    student_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    reason_id: uuid.UUID | None = None
    level: str | None = None
    group_id: uuid.UUID | None = None
    staff_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    note: str = Field(default="", max_length=1000)

    @field_validator("level")
    @classmethod
    def _level(cls, value: str | None) -> str | None:
        return value if value in LEVELS else None

    @field_validator("time", mode="before")
    @classmethod
    def _empty_time(cls, value):
        return value or None


class SchedulePatch(ScheduleIn):
    status: Literal["agendada", "no_se_hizo"] = "agendada"


class Person(BaseModel):
    id: uuid.UUID
    name: str


class Student(Person):
    curso: str | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    date: dt.date
    time: str | None
    kind: str
    title: str
    family_id: uuid.UUID | None
    family_name: str | None
    students: list[Student]
    reason_id: uuid.UUID | None
    reason_name: str | None
    level: str | None
    group_id: uuid.UUID | None
    group_name: str | None
    staff: list[Person]
    note: str
    status: str
    created_by: uuid.UUID
    created_by_name: str
    meeting_id: uuid.UUID | None
    # Estado de la reunión grabada (live, paused, processing, completed...) y de su acta.
    meeting_status: str | None
    minutes_status: str | None
    can_edit: bool


def _visible(scope: Scope, everything_of_level: bool):
    """Lo propio, a lo que me sumaron y lo de mis grupos; con "Todo mi nivel", también eso."""
    me = str(scope.user_id)
    mine = or_(
        ScheduledMeeting.created_by == scope.user_id,
        ScheduledMeeting.staff_ids.contains([me]),
        and_(ScheduledMeeting.kind == "interna", ScheduledMeeting.group_id.in_(scope.groups))
        if scope.groups
        else false(),
    )
    if not everything_of_level:
        return mine
    if scope.sees_everything:
        return or_(mine, ScheduledMeeting.kind == "familia")
    levels = scope.full_levels
    by_level = (
        and_(ScheduledMeeting.kind == "familia", ScheduledMeeting.level.in_(levels)) if levels else false()
    )
    return or_(mine, by_level)


def _can_edit(scope: Scope, item: ScheduledMeeting) -> bool:
    return (
        item.created_by == scope.user_id
        or str(scope.user_id) in (item.staff_ids or [])
        or scope.sees_everything
    )


async def _check_refs(db: AsyncSession, ctx: OrgContext, scope: Scope, data: ScheduleIn) -> None:
    """Lo que se nombra tiene que ser de esta sede (y el grupo, de quien agenda)."""
    if data.family_id is not None:
        family = await db.get(Family, data.family_id)
        if family is None or family.organization_id != ctx.org_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Familia no encontrada")
    if data.reason_id is not None:
        reason = await db.get(MeetingReason, data.reason_id)
        if reason is None or reason.organization_id != ctx.org_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Motivo no encontrado")
    if data.kind == "interna":
        if data.group_id is None or (data.group_id not in scope.groups and not scope.sees_everything):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo se agenda para un grupo del que sos parte")


async def _out(db: AsyncSession, scope: Scope, items: list[ScheduledMeeting]) -> list[ScheduleOut]:
    """Todo lo que la lista muestra, en pocas idas a la base."""
    family_ids = {item.family_id for item in items if item.family_id}
    reason_ids = {item.reason_id for item in items if item.reason_id}
    group_ids = {item.group_id for item in items if item.group_id}
    meeting_ids = {item.meeting_id for item in items if item.meeting_id}
    student_ids = {uuid.UUID(sid) for item in items for sid in item.student_ids or []}
    user_ids = {item.created_by for item in items} | {uuid.UUID(uid) for item in items for uid in item.staff_ids or []}

    async def names(model, ids, *columns):
        if not ids:
            return {}
        rows = (await db.execute(select(model.id, *columns).where(model.id.in_(ids)))).all()
        return {row[0]: row[1:] for row in rows}

    families = await names(Family, family_ids, Family.name)
    reasons = await names(MeetingReason, reason_ids, MeetingReason.name)
    groups = await names(InternalGroup, group_ids, InternalGroup.name)
    users = await names(User, user_ids, User.name)
    students = await names(FamilyMember, student_ids, FamilyMember.name, FamilyMember.curso)
    meetings = await names(Meeting, meeting_ids, Meeting.status)
    minutes = {}
    if meeting_ids:
        rows = (await db.execute(select(Minutes.meeting_id, Minutes.status).where(Minutes.meeting_id.in_(meeting_ids)))).all()
        minutes = {row[0]: row[1] for row in rows}

    out = []
    for item in items:
        staff = [uuid.UUID(uid) for uid in item.staff_ids or []]
        kids = [uuid.UUID(sid) for sid in item.student_ids or []]
        out.append(
            ScheduleOut(
                id=item.id,
                date=item.date,
                time=item.time,
                kind=item.kind,
                title=item.title,
                family_id=item.family_id,
                family_name=families.get(item.family_id, (None,))[0],
                students=[Student(id=sid, name=students[sid][0], curso=students[sid][1]) for sid in kids if sid in students],
                reason_id=item.reason_id,
                reason_name=reasons.get(item.reason_id, (None,))[0],
                level=item.level,
                group_id=item.group_id,
                group_name=groups.get(item.group_id, (None,))[0],
                staff=[Person(id=uid, name=users[uid][0]) for uid in staff if uid in users],
                note=item.note,
                status=item.status,
                created_by=item.created_by,
                created_by_name=users.get(item.created_by, ("",))[0],
                meeting_id=item.meeting_id,
                meeting_status=meetings.get(item.meeting_id, (None,))[0],
                minutes_status=minutes.get(item.meeting_id),
                can_edit=_can_edit(scope, item),
            )
        )
    return out


def _order(query):
    # Sin hora va después de las que tienen hora, en el orden en que se agendaron.
    return query.order_by(ScheduledMeeting.date, ScheduledMeeting.time.asc().nulls_last(), ScheduledMeeting.created_at)


@router.get("", response_model=list[ScheduleOut])
async def list_agenda(
    start: dt.date,
    end: dt.date,
    scope_name: Literal["mine", "nivel"] = Query(default="mine", alias="scope"),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rango de fechas inválido")
    scope = await ctx.scope(db)
    query = select(ScheduledMeeting).where(
        ScheduledMeeting.organization_id == ctx.org_id,
        ScheduledMeeting.date >= start,
        ScheduledMeeting.date <= end,
        _visible(scope, scope_name == "nivel"),
    )
    items = (await db.execute(_order(query))).scalars().all()
    return await _out(db, scope, list(items))


@router.get("/pending", response_model=list[ScheduleOut])
async def pending(
    today: dt.date,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Las mías de los últimos 30 días que no se empezaron ni se descartaron."""
    scope = await ctx.scope(db)
    query = select(ScheduledMeeting).where(
        ScheduledMeeting.organization_id == ctx.org_id,
        ScheduledMeeting.date < today,
        ScheduledMeeting.date >= today - timedelta(days=30),
        ScheduledMeeting.status == "agendada",
        ScheduledMeeting.meeting_id.is_(None),
        _visible(scope, False),
    )
    items = (await db.execute(_order(query))).scalars().all()
    return await _out(db, scope, list(items))


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    data: ScheduleIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("member")
    scope = await ctx.scope(db)
    await _check_refs(db, ctx, scope, data)
    item = ScheduledMeeting(organization_id=ctx.org_id, created_by=ctx.user.id, **_values(data))
    db.add(item)
    await db.flush()
    await audit(db, ctx.org_id, ctx.user.id, "agenda.create", "scheduled_meeting", str(item.id))
    await db.commit()
    await db.refresh(item)
    return (await _out(db, scope, [item]))[0]


def _values(data: ScheduleIn) -> dict:
    familia = data.kind == "familia"
    return {
        "date": data.date,
        "time": data.time,
        "kind": data.kind,
        "title": data.title.strip(),
        "family_id": data.family_id if familia else None,
        "student_ids": [str(sid) for sid in data.student_ids] if familia and data.family_id else [],
        "reason_id": data.reason_id if familia else None,
        "level": data.level if familia else None,
        "group_id": data.group_id if not familia else None,
        "staff_ids": [str(uid) for uid in dict.fromkeys(data.staff_ids)],
        "note": data.note.strip(),
    }


async def _editable(db: AsyncSession, ctx: OrgContext, item_id: uuid.UUID) -> tuple[ScheduledMeeting, Scope]:
    item = await db.get(ScheduledMeeting, item_id)
    scope = await ctx.scope(db)
    if item is None or item.organization_id != ctx.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reunión agendada no encontrada")
    if not _can_edit(scope, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cambia quien la agendó o quienes van")
    return item, scope


@router.put("/{item_id}", response_model=ScheduleOut)
async def update_schedule(
    item_id: uuid.UUID,
    data: SchedulePatch,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    item, scope = await _editable(db, ctx, item_id)
    await _check_refs(db, ctx, scope, data)
    for key, value in _values(data).items():
        setattr(item, key, value)
    item.status = data.status
    await audit(db, ctx.org_id, ctx.user.id, "agenda.update", "scheduled_meeting", str(item.id))
    await db.commit()
    await db.refresh(item)
    return (await _out(db, scope, [item]))[0]


class MovePatch(BaseModel):
    date: dt.date | None = None
    status: Literal["agendada", "no_se_hizo"] | None = None


@router.patch("/{item_id}", response_model=ScheduleOut)
async def move_schedule(
    item_id: uuid.UUID,
    data: MovePatch,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Pasar a otro día o marcar que no se hizo, sin tocar lo demás."""
    item, scope = await _editable(db, ctx, item_id)
    if data.date is not None:
        item.date = data.date
        item.status = "agendada"
    if data.status is not None:
        item.status = data.status
    await db.commit()
    await db.refresh(item)
    return (await _out(db, scope, [item]))[0]


@router.delete("/{item_id}", status_code=204)
async def delete_schedule(
    item_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    item, _ = await _editable(db, ctx, item_id)
    await audit(db, ctx.org_id, ctx.user.id, "agenda.delete", "scheduled_meeting", str(item.id))
    await db.delete(item)
    await db.commit()


async def link_meeting(db: AsyncSession, ctx: OrgContext, item_id: uuid.UUID, meeting: Meeting) -> None:
    """Al tocar "Empezar": la reunión agendada queda enlazada a la grabada."""
    item = await db.get(ScheduledMeeting, item_id)
    if item is None or item.organization_id != ctx.org_id or item.meeting_id is not None:
        return
    if not _can_edit(await ctx.scope(db), item):
        return
    item.meeting_id = meeting.id
    item.status = "agendada"
