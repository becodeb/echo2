""""Olvidé mi contraseña".

- POST /api/auth/password/forgot: siempre responde lo mismo (no dice si el
  mail existe). Si la cuenta existe, crea un link de un solo uso que vence en
  una hora y lo manda por mail. Mientras no haya mail configurado (Resend o
  SMTP), el pedido le llega a Becode por la campanita, con el link, para que
  se lo reenvíe a la persona.
- POST /api/auth/password/reset: con el link, la contraseña nueva. Cierra las
  otras sesiones abiertas.
"""
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import rate_limit
from ..models import Notification, OrganizationMember, PasswordReset, RefreshToken, User
from ..security import hash_password, hash_refresh_token
from ..services.audit import audit
from ..services.background import spawn
from ..services.mailer import mail_enabled, send_mail

router = APIRouter(prefix="/api/auth/password", tags=["auth"])

RESET_MINUTES = 60


class ForgotIn(BaseModel):
    email: EmailStr


@router.post("/forgot", status_code=202)
async def forgot_password(data: ForgotIn, request: Request, db: AsyncSession = Depends(get_db)):
    rate_limit(f"forgot:{request.client.host if request.client else 'x'}", 5, window_seconds=600)
    email = str(data.email).lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active or user.deleted_at is not None:
        return {"ok": True}
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(user_id=user.id, token_hash=hash_refresh_token(token),
                         expires_at=datetime.now(UTC) + timedelta(minutes=RESET_MINUTES)))
    link = f"{get_settings().web_origin.rstrip('/')}/restablecer?token={token}"
    body = (
        f"Hola, {user.name.split(' ')[0]}.\n\nPara elegir una contraseña nueva para Echo, entrá a este link "
        f"(vence en una hora y sirve una sola vez):\n\n{link}\n\nSi no lo pediste vos, ignorá este mail."
    )
    if mail_enabled():
        spawn(send_mail(user.email, "Echo: elegí una contraseña nueva", body), name="mail:reset")
    else:
        # Sin mail configurado: Becode se lo reenvía a mano.
        admins = (await db.execute(select(User.id).where(User.is_superadmin.is_(True)))).scalars().all()
        for admin_id in admins:
            org_id = (
                await db.execute(
                    select(OrganizationMember.organization_id).where(OrganizationMember.user_id == admin_id).limit(1)
                )
            ).scalar_one_or_none()
            if org_id is not None:
                db.add(Notification(
                    user_id=admin_id, organization_id=org_id, kind="password_reset",
                    title=f"{user.email} pidió una contraseña nueva",
                    body=f"Todavía no hay mail configurado: mandale este link (vence en una hora):\n\n{link}",
                ))
    await audit(db, None, user.id, "user.password_forgot", "user", str(user.id))
    await db.commit()
    return {"ok": True}


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/reset")
async def reset_password(data: ResetIn, db: AsyncSession = Depends(get_db)):
    now = datetime.now(UTC)
    reset = (
        await db.execute(
            select(PasswordReset).where(PasswordReset.token_hash == hash_refresh_token(data.token)).with_for_update()
        )
    ).scalar_one_or_none()
    if reset is None or reset.used_at is not None or reset.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El link venció o ya se usó. Pedí uno nuevo.")
    user = await db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El link venció o ya se usó. Pedí uno nuevo.")
    user.password_hash = hash_password(data.password)
    reset.used_at = now
    # Las sesiones abiertas (por ejemplo, de quien adivinó la contraseña vieja) se cierran.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await audit(db, None, user.id, "user.password_reset", "user", str(user.id))
    await db.commit()
    return {"ok": True}
