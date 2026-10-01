"""Mails que manda el servidor: por Resend (RESEND_API_KEY) o por SMTP.

Hoy: avisos a Becode (pedidos de plan, contacto) y el link de "Olvidé mi
contraseña". Sin ninguno configurado no manda nada y lo deja en el log: lo
importante igual queda en la base y en la campanita de los superadmins.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger("echo.mailer")


def _send(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.mail_from or settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ssl.create_default_context(), timeout=20) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def mail_enabled() -> bool:
    settings = get_settings()
    return bool(settings.resend_api_key or settings.smtp_host)


async def _send_resend(to: str, subject: str, body: str) -> None:
    import httpx

    settings = get_settings()
    sender = settings.mail_from or settings.smtp_from or "Echo <no-responder@becode.com.ar>"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": sender, "to": [to], "subject": subject, "text": body},
        )
        response.raise_for_status()


async def send_mail(to: str, subject: str, body: str) -> bool:
    """True si salió. Nunca levanta: un mail que no sale no corta nada."""
    if not mail_enabled() or not to:
        log.info("mail sin Resend ni SMTP configurado (no se manda): %s", subject)
        return False
    try:
        if get_settings().resend_api_key:
            await _send_resend(to, subject, body)
        else:
            await asyncio.to_thread(_send, to, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("no se pudo mandar el mail %r: %s", subject, exc)
        return False
