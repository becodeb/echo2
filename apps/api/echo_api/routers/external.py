"""Tareas para gente de afuera de Echo.

Quien ve una tarea se la puede asignar a alguien sin cuenta (una terapeuta, un
docente de otra institución) con su mail. A esa persona le llega un mail
("Ana te asignó esta tarea: …") con un link personal, y con ese link ve lo
que eligió quien se la asignó:

- task:    solo la tarea;
- acta:    la tarea y el acta de la reunión;
- meeting: la tarea y la reunión entera (resumen, acta y transcripción).

El audio nunca: no vive en Echo (services/recording.py). Desde el link puede
marcar la tarea como hecha, y quien se la asignó recibe el aviso. El link se
revoca desde la tarea; del token se guarda solo el hash.
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_org_context, rate_limit
from ..models import (
    ActionItem,
    ExternalAccess,
    Meeting,
    MeetingSummary,
    Minutes,
    MinutesVersion,
    Notification,
    Organization,
    Speaker,
    TranscriptSegment,
    User,
)
from ..security import hash_refresh_token
from ..services.audit import audit
from ..services.mailer import mail_enabled, send_mail
from .tasks import _task_or_404

router = APIRouter(tags=["external"])

# Lo que dura el link. Largo a propósito: una tarea con una terapeuta puede
# llevar meses, y se revoca a mano cuando haga falta.
ACCESS_DAYS = 180

SCOPE_LABEL = {
    "task": "solo la tarea",
    "acta": "la tarea y el acta",
    "meeting": "la tarea y la reunión completa",
}


class ExternalAssignIn(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=200)
    scope: str = Field(default="task", pattern="^(task|acta|meeting)$")


class ExternalAccessOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    scope: str
    created_at: datetime
    last_seen_at: datetime | None
    mail_sent: bool
    # Solo al crearlo: después no se puede volver a armar (se guarda el hash).
    link: str | None = None


def _access_out(access: ExternalAccess, link: str | None = None) -> ExternalAccessOut:
    return ExternalAccessOut(
        id=access.id,
        email=access.email,
        name=access.name,
        scope=access.scope,
        created_at=access.created_at,
        last_seen_at=access.last_seen_at,
        mail_sent=access.mail_sent,
        link=link,
    )


def _mail_body(
    who: str, org: str, first_name: str, task: ActionItem, meeting: Meeting | None, scope: str, link: str
) -> str:
    lines = [f"Hola{', ' + first_name if first_name else ''}.", "", f"{who} ({org}) te asignó esta tarea:", "", task.text]
    if task.due_date:
        lines += ["", f"Para el {task.due_date.strftime('%d/%m/%Y')}."]
    elif task.due_text:
        lines += ["", f"Para: {task.due_text}."]
    if meeting is not None:
        lines += ["", f"Surgió en la reunión «{meeting.title}»."]
    seen = {"task": "Podés verla", "acta": "Podés verla junto con el acta", "meeting": "Podés verla junto con la reunión"}
    lines += [
        "",
        f"{seen[scope]} y marcarla como hecha acá:",
        link,
        "",
        "El link es personal: no lo reenvíes.",
        "",
        "— Echo",
    ]
    return "\n".join(lines)


@router.post("/api/tasks/{task_id}/external", response_model=ExternalAccessOut, status_code=201)
async def assign_external(
    task_id: uuid.UUID,
    data: ExternalAssignIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    rate_limit(f"external:{ctx.user.id}", 30, window_seconds=3600)
    task = await _task_or_404(db, ctx, task_id)
    if data.scope != "task" and task.meeting_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta tarea no es de ninguna reunión: solo se puede compartir la tarea")
    email = str(data.email).lower()
    name = (data.name or "").strip() or None

    # Un solo link vivo por persona y tarea: reasignar a la misma persona con
    # otro acceso reemplaza el anterior.
    for previous in (
        await db.execute(
            select(ExternalAccess).where(
                ExternalAccess.task_id == task.id,
                ExternalAccess.email == email,
                ExternalAccess.revoked_at.is_(None),
            )
        )
    ).scalars():
        previous.revoked_at = datetime.now(UTC)

    token = secrets.token_urlsafe(32)
    access = ExternalAccess(
        organization_id=ctx.org_id,
        meeting_id=task.meeting_id,
        task_id=task.id,
        email=email,
        name=name,
        scope=data.scope,
        token_hash=hash_refresh_token(token),
        created_by=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=ACCESS_DAYS),
    )
    db.add(access)
    task.assignee_user_id = None
    task.assignee_email = email
    task.assignee_name = name or email
    task.source = "manual" if task.source == "ai" else task.source

    meeting = await db.get(Meeting, task.meeting_id) if task.meeting_id else None
    link = f"{get_settings().web_origin.rstrip('/')}/t/{token}"
    body = _mail_body(
        ctx.user.name, ctx.org.name, (name or "").split(" ")[0], task, meeting, data.scope, link
    )
    await db.flush()
    await audit(db, ctx.org_id, ctx.user.id, "task.external_assign", "task", str(task.id),
                detail={"email": email, "scope": data.scope})
    await db.commit()
    # El mail sale después de guardar: si Resend tarda o falla, la tarea ya
    # quedó asignada y el link se puede copiar a mano desde la pantalla.
    if mail_enabled():
        access.mail_sent = await send_mail(
            email, f"{ctx.user.name} te asignó una tarea", body, reply_to=ctx.user.email
        )
        await db.commit()
    await db.refresh(access)
    return _access_out(access, link)


@router.get("/api/tasks/{task_id}/external", response_model=list[ExternalAccessOut])
async def list_external(
    task_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _task_or_404(db, ctx, task_id)
    rows = (
        await db.execute(
            select(ExternalAccess)
            .where(ExternalAccess.task_id == task.id, ExternalAccess.revoked_at.is_(None))
            .order_by(ExternalAccess.created_at.desc())
        )
    ).scalars()
    return [_access_out(row) for row in rows]


@router.delete("/api/external-access/{access_id}", status_code=204)
async def revoke_external(
    access_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    access = await db.get(ExternalAccess, access_id)
    if access is None or access.organization_id != ctx.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Acceso no encontrado")
    if access.task_id:
        await _task_or_404(db, ctx, access.task_id)
    access.revoked_at = datetime.now(UTC)
    await audit(db, ctx.org_id, ctx.user.id, "task.external_revoke", "task", str(access.task_id),
                detail={"email": access.email})
    await db.commit()


# ── La vista de quien recibió el link (sin cuenta) ───────────────


async def _access_by_token(db: AsyncSession, token: str) -> ExternalAccess:
    access = (
        await db.execute(select(ExternalAccess).where(ExternalAccess.token_hash == hash_refresh_token(token)))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if access is None or access.revoked_at is not None or (access.expires_at and access.expires_at < now):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Este link ya no es válido. Pedile uno nuevo a quien te asignó la tarea.")
    return access


async def _minutes_markdown(db: AsyncSession, meeting_id: uuid.UUID) -> str | None:
    minutes = (await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))).scalar_one_or_none()
    if not minutes:
        return None
    version = (
        await db.execute(
            select(MinutesVersion).where(
                MinutesVersion.minutes_id == minutes.id, MinutesVersion.version == minutes.current_version
            )
        )
    ).scalar_one_or_none()
    if not version:
        return None
    if minutes.number is not None:
        return f"**Acta N.º {minutes.number}**\n\n{version.body_markdown}"
    return version.body_markdown


@router.get("/api/external/{token}")
async def view_external(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    rate_limit(f"external-view:{request.client.host if request.client else 'x'}", 60)
    access = await _access_by_token(db, token)
    task = await db.get(ActionItem, access.task_id) if access.task_id else None
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La tarea ya no existe")
    meeting = await db.get(Meeting, access.meeting_id) if access.meeting_id else None
    if meeting is not None and meeting.deleted_at is not None:
        meeting = None
    org = await db.get(Organization, access.organization_id)
    assigner = await db.get(User, access.created_by)
    access.last_seen_at = datetime.now(UTC)

    out: dict = {
        "scope": access.scope,
        "scope_label": SCOPE_LABEL[access.scope],
        "organization": org.name if org else None,
        "assigned_by": assigner.name if assigner else None,
        "assignee": access.name or access.email,
        "task": {
            "text": task.text,
            "status": task.status,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "due_text": task.due_text,
        },
        "meeting": None,
        "minutes_markdown": None,
        "executive_summary": None,
        "transcript": None,
    }
    if meeting is not None:
        out["meeting"] = {
            "title": meeting.title,
            "started_at": (meeting.started_at or meeting.created_at).isoformat(),
            "duration_seconds": meeting.duration_seconds,
        }
        if access.scope in ("acta", "meeting"):
            out["minutes_markdown"] = await _minutes_markdown(db, meeting.id)
        if access.scope == "meeting":
            summary = (
                await db.execute(
                    select(MeetingSummary).where(
                        MeetingSummary.meeting_id == meeting.id, MeetingSummary.kind == "executive"
                    )
                )
            ).scalar_one_or_none()
            out["executive_summary"] = summary.content if summary else None
            segments = (
                await db.execute(
                    select(TranscriptSegment, Speaker)
                    .outerjoin(Speaker, Speaker.id == TranscriptSegment.speaker_id)
                    .where(TranscriptSegment.meeting_id == meeting.id, TranscriptSegment.is_final.is_(True))
                    .order_by(TranscriptSegment.seq)
                    .limit(3000)
                )
            ).all()
            out["transcript"] = [
                {"start_ms": s.start_ms, "speaker": (sp.display_name or sp.label) if sp else None, "text": s.text}
                for s, sp in segments
            ]
    await db.commit()
    return out


class ExternalStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|done)$")


@router.post("/api/external/{token}/status")
async def external_status(token: str, data: ExternalStatusIn, request: Request, db: AsyncSession = Depends(get_db)):
    rate_limit(f"external-status:{request.client.host if request.client else 'x'}", 20)
    access = await _access_by_token(db, token)
    task = await db.get(ActionItem, access.task_id) if access.task_id else None
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La tarea ya no existe")
    if task.status != data.status:
        task.status = data.status
        if data.status == "done":
            db.add(
                Notification(
                    user_id=access.created_by,
                    organization_id=access.organization_id,
                    kind="task_done",
                    title=f"{access.name or access.email} terminó una tarea",
                    body=task.text[:200],
                    link=f"/meetings/{task.meeting_id}" if task.meeting_id else "/tasks",
                )
            )
        await audit(db, access.organization_id, None, "task.external_status", "task", str(task.id),
                    detail={"email": access.email, "status": data.status})
    await db.commit()
    return {"status": task.status}
