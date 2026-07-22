from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ...models import AppSettings, Hit
from ..email.subject import coverage_subject


logger = logging.getLogger(__name__)
SMTP_URL = os.getenv("SMTP_URL", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "coverage@shift6.local")
UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:5173")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def _valid_email(value: str) -> bool:
    parsed = parseaddr(value)[1]
    return bool(parsed and "@" in parsed and parsed.rsplit("@", 1)[1])


def _send_raw(to_addrs: list[str], subject: str, body: str) -> bool:
    if not SMTP_URL or not to_addrs or not all(_valid_email(item) for item in to_addrs):
        return False
    try:
        parsed = urlparse(SMTP_URL)
        if parsed.scheme not in {"smtp", "smtps"} or not parsed.hostname:
            raise ValueError("SMTP_URL must use smtp:// or smtps://")
        port = parsed.port or (465 if parsed.scheme == "smtps" else 587)
        context = ssl.create_default_context()
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = FROM_EMAIL
        message["To"] = ", ".join(to_addrs)
        message.set_content(body)

        if parsed.scheme == "smtps":
            with smtplib.SMTP_SSL(parsed.hostname, port, timeout=20, context=context) as connection:
                if parsed.username and parsed.password:
                    connection.login(parsed.username, parsed.password)
                connection.send_message(message)
        else:
            with smtplib.SMTP(parsed.hostname, port, timeout=20) as connection:
                connection.ehlo()
                connection.starttls(context=context)
                connection.ehlo()
                if parsed.username and parsed.password:
                    connection.login(parsed.username, parsed.password)
                connection.send_message(message)
        return True
    except Exception:
        logger.exception("Coverage email delivery failed")
        return False


def send_hit_email(db: Session, hit: Hit) -> bool:
    if not hit.source_verified:
        return False
    settings = db.query(AppSettings).first()
    if not settings or not settings.email_enabled:
        return False
    recipients = [item.strip() for item in (settings.emails or "").split(",") if item.strip()]
    subject = coverage_subject(hit.url or "", hit.domain, hit.title)
    body = (
        f"Outlet: {hit.domain or ''}\n"
        f"Title: {hit.title or ''}\n"
        f"Client: {hit.client_name or ''}\n"
        f"Match: {hit.match_type or ''}\n"
        f"Source verified: yes\n"
        f"Snippet: {(hit.snippet or '')[:280]}\n"
        f"Open: {API_BASE_URL}/api/v1/coverage/r/{hit.id}\n"
        f"Coverage List: {UI_BASE_URL}/coverage\n"
    )
    return _send_raw(recipients, subject, body)


def deliver_hit_email(db: Session, hit: Hit) -> bool:
    claimed = (
        db.query(Hit)
        .filter(
            Hit.id == hit.id,
            Hit.source_verified.is_(True),
            Hit.email_delivery_status == "pending",
        )
        .update(
            {"email_delivery_status": "sending", "email_attempted_at": datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        return False
    db.refresh(hit)
    sent = send_hit_email(db, hit)
    hit.email_delivery_status = "sent" if sent else "failed"
    if sent:
        hit.emailed_at = datetime.now(timezone.utc)
    db.commit()
    return sent
