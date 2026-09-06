"""Yiriba SaaS — Envoi d'emails transactionnels.

Deux providers supportés (voir EMAIL_PROVIDER dans .env) :
  - "resend" : API REST Resend (clé re_...), recommandé.
  - "smtp"   : smtplib compatible tout serveur SMTP.
Si aucun fournisseur n'est configuré, le contenu est loggé (mode dev).
"""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings

logger = logging.getLogger("yiriba")


def send_email(to_address: str, subject: str, html: str) -> bool:
    """Envoie un email HTML. Retourne True si le mail a ete envoye."""
    settings = get_settings()

    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
        return _send_via_resend(
            api_key=settings.RESEND_API_KEY,
            from_address=settings.RESEND_FROM,
            to_address=to_address,
            subject=subject,
            html=html,
        )

    if not settings.smtp_configured:
        logger.info(
            "[EMAIL SIMULE - aucun fournisseur configure] A: %s | Sujet: %s\n%s",
            to_address,
            subject,
            html,
        )
        return False

    return _send_via_smtp(settings, to_address, subject, html)


def _send_via_resend(
    api_key: str, from_address: str, to_address: str, subject: str, html: str
) -> bool:
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": from_address,
                "to": [to_address],
                "subject": subject,
                "html": html,
            },
            timeout=20,
        )
        if resp.status_code < 300:
            logger.info("Email envoye via Resend a %s (sujet: %s)", to_address, subject)
            return True
        logger.error(
            "Resend a refuse l'email a %s: %s - %s",
            to_address,
            resp.status_code,
            resp.text[:300],
        )
        return False
    except Exception:
        logger.exception("Echec envoi email Resend a %s", to_address)
        return False


def _send_via_smtp(settings, to_address: str, subject: str, html: str) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_address
    msg.set_content(html, subtype="html")

    try:
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.starttls()
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        logger.info("Email envoye via SMTP a %s (sujet: %s)", to_address, subject)
        return True
    except Exception:
        logger.exception("Echec envoi email SMTP a %s", to_address)
        return False
