"""Mails que manda el servidor (SMTP). Hoy: el aviso a Becode de un pedido de plan.

Sin SMTP_HOST configurado no manda nada y lo deja en el log: el pedido igual
queda en la base y en el panel de superadmin, así que no se pierde.
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
    message["From"] = settings.smtp_from or settings.smtp_user
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


async def send_mail(to: str, subject: str, body: str) -> bool:
    """True si salió. Nunca levanta: un mail que no sale no corta nada."""
    if not get_settings().smtp_host or not to:
        log.info("mail sin SMTP configurado (no se manda): %s", subject)
        return False
    try:
        await asyncio.to_thread(_send, to, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("no se pudo mandar el mail %r: %s", subject, exc)
        return False
