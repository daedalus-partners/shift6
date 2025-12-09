from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session

from ...models import AppSettings, Hit


SMTP_URL = os.getenv("SMTP_URL", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "coverage@shift6.local")
UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:5173")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def _send_raw(to_addrs: list[str], subject: str, body: str) -> bool:
    if not SMTP_URL:
        return False
    try:
        # SMTP_URL format: smtp://user:pass@host:port or smtps://...
        # We handle plain SMTP with optional TLS on 587.
        import urllib.parse as up

        u = up.urlparse(SMTP_URL)
        host = u.hostname or "localhost"
        port = u.port or (465 if u.scheme == "smtps" else 25)
        user = u.username
        pwd = u.password
        use_tls = (u.scheme == "smtps") or (port == 465)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = FROM_EMAIL
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(body)

        if use_tls:
            with smtplib.SMTP_SSL(host, port) as s:
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as s:
                try:
                    s.starttls()
                except Exception:
                    pass
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception:
        return False


def send_hit_email(db: Session, hit: Hit) -> bool:
    settings = db.query(AppSettings).first()
    if not settings or not settings.email_enabled or not (settings.emails or "").strip():
        return False
    to_list = [e.strip() for e in settings.emails.split(",") if e.strip()]
    if not to_list:
        return False

    subject = f"Coverage: {hit.domain or ''} — {hit.title or hit.url}"
    coverage_url = f"{UI_BASE_URL}/coverage"
    direct = f"{API_BASE_URL}/api/v1/coverage/r/{hit.id}"
    body = (
        f"Outlet: {hit.domain or ''}\n"
        f"Title: {hit.title or ''}\n"
        f"Client: {hit.client_name or ''}\n"
        f"Match: {hit.match_type or ''}\n"
        f"Snippet: {(hit.snippet or '')[:280]}\n"
        f"Open: {direct}\n"
        f"Coverage List: {coverage_url}\n"
    )
    return _send_raw(to_list, subject, body)

