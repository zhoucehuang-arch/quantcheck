from __future__ import annotations

import base64
import mimetypes
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))


def parse_recipients(value: str | Iterable[str] | None, default: str | None = None) -> List[str]:
    default = default or os.environ.get("NOTIFY_EMAIL_TO", "")
    if value is None:
        raw_items = [default] if default else []
    elif isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    else:
        raw_items = []
        for item in value:
            raw_items.extend(str(item).replace(";", ",").split(","))
    recipients: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        addr = item.strip()
        if not addr or addr in seen:
            continue
        recipients.append(addr)
        seen.add(addr)
    return recipients


def _build_message(sender: str, recipients: list[str], subject: str, body: str, attachments: Iterable[Path] | None = None, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body or "")
    if html:
        msg.add_alternative(html, subtype="html")
    for p in attachments or []:
        path = Path(p)
        if not path.exists() or not path.is_file():
            continue
        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


def send_via_smtp(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, timeout: int = 30, html: str | None = None) -> bool:
    recipients = parse_recipients(to)
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "465"))
    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM") or username
    use_tls = os.environ.get("SMTP_USE_TLS", "1") != "0"
    starttls = os.environ.get("SMTP_STARTTLS", "0") == "1"
    if not (recipients and host and sender):
        return False
    try:
        msg = _build_message(sender, recipients, subject, body, attachments, html)
        if use_tls and not starttls:
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context()) as s:
                if username:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as s:
                if starttls:
                    s.starttls(context=ssl.create_default_context())
                if username:
                    s.login(username, password)
                s.send_message(msg)
        return True
    except Exception:
        return False


def send_via_gmail_api(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, timeout: int = 120, html: str | None = None) -> bool:
    """Send with Gmail API when google client libraries and OAuth token are configured.

    Required env/config:
      GMAIL_API_ENABLED=1
      GMAIL_API_CLIENT_SECRET=/path/client_secret.json
      GMAIL_API_TOKEN=/path/token.json
      GMAIL_API_FROM=sender@example.com
    """
    if os.environ.get("GMAIL_API_ENABLED", "0") != "1":
        return False
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except Exception:
        return False
    recipients = parse_recipients(to)
    sender = os.environ.get("GMAIL_API_FROM") or os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME")
    token_path = Path(os.environ.get("GMAIL_API_TOKEN", ROOT / ".config" / "gmail-api" / "token.json"))
    if not (recipients and sender and token_path.exists()):
        return False
    scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        if not creds.valid:
            return False
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = _build_message(sender, recipients, subject, body, attachments, html)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception:
        return False


def send_email(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, html: str | None = None) -> bool:
    return send_via_gmail_api(subject, body, to=to, attachments=attachments, html=html) or send_via_smtp(subject, body, to=to, attachments=attachments, html=html)
