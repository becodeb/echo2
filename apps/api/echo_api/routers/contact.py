"""Contacto con Becode sin mostrar ningún mail, y pedido de baja de la cuenta.

- POST /api/contact: público (landing, Privacidad). Ventas, ejercer derechos
  sobre los datos (Ley 25.326), soporte. Llega a la campanita de los
  superadmins y por mail a SALES_EMAIL.
- GET/POST /api/me/deletion-request: "Pedir la baja de mi cuenta" (Ajustes →
  Privacidad). Becode la procesa a mano dentro de los 5 días hábiles que fija
  la ley: borrar sola una cuenta podría llevarse reuniones de un colegio.
"""
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, rate_limit
from ..models import AuditLog, Notification, OrganizationMember, User
from ..services.audit import audit
from ..services.background import spawn
from ..services.mailer import send_mail

log = logging.getLogger("echo.contact")

router = APIRouter(tags=["contact"])

TOPICS = {
    "ventas": "Planes e instituciones",
    "privacidad": "Mis datos (acceso, corrección o baja)",
    "soporte": "Ayuda con Echo",
    "otro": "Otro tema",
}


async def _tell_becode(db: AsyncSession, title: str, body: str, link: str) -> None:
    """Campanita de cada superadmin (en su primera organización) y mail a ventas."""
    admins = (await db.execute(select(User.id).where(User.is_superadmin.is_(True)))).scalars().all()
    for admin_id in admins:
        org_id = (
            await db.execute(
                select(OrganizationMember.organization_id).where(OrganizationMember.user_id == admin_id).limit(1)
            )
        ).scalar_one_or_none()
        if org_id is not None:
            db.add(Notification(user_id=admin_id, organization_id=org_id, kind="contact",
                                title=title[:300], body=body, link=link))
    spawn(send_mail(get_settings().sales_email, f"[Echo] {title}", body), name="mail:contact")


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    topic: Literal["ventas", "privacidad", "soporte", "otro"] = "otro"
    organization: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    # Trampa para bots: un campo oculto que una persona nunca completa.
    website: str | None = Field(default=None, max_length=200)


@router.post("/api/contact", status_code=202)
async def contact(data: ContactIn, request: Request, db: AsyncSession = Depends(get_db)):
    rate_limit(f"contact:{request.client.host if request.client else 'x'}", 5, window_seconds=600)
    if data.website:
        return {"ok": True}
    title = f"Contacto: {TOPICS[data.topic]} — {data.name.strip()}"
    body = (
        f"{data.name.strip()} <{data.email}>"
        + (f" · {data.organization.strip()}" if data.organization and data.organization.strip() else "")
        + f"\nTema: {TOPICS[data.topic]}\n\n{data.message.strip()}"
    )
    await _tell_becode(db, title, body, "/admin")
    await audit(db, None, None, "contact.message", "contact", data.topic,
                detail={"email": data.email, "topic": data.topic})
    await db.commit()
    return {"ok": True}


class DeletionOut(BaseModel):
    requested_at: datetime | None


async def _last_request(db: AsyncSession, user_id) -> datetime | None:
    return (
        await db.execute(
            select(AuditLog.created_at)
            .where(AuditLog.actor_id == user_id, AuditLog.action == "account.deletion_request")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/api/me/deletion-request", response_model=DeletionOut)
async def deletion_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return DeletionOut(requested_at=await _last_request(db, user.id))


@router.post("/api/me/deletion-request", response_model=DeletionOut)
async def request_deletion(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    previous = await _last_request(db, user.id)
    if previous is not None:
        return DeletionOut(requested_at=previous)
    orgs = (
        await db.execute(select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id))
    ).scalars().all()
    await _tell_becode(
        db,
        f"{user.name} pidió la baja de su cuenta",
        f"{user.name} <{user.email}> pidió la baja de su cuenta de Echo.\n"
        f"Organizaciones: {len(orgs)}.\n\nPlazo legal (Ley 25.326, art. 16): 5 días hábiles.",
        "/admin",
    )
    await audit(db, None, user.id, "account.deletion_request", "user", str(user.id), detail={"email": user.email})
    await db.commit()
    return DeletionOut(requested_at=await _last_request(db, user.id))
