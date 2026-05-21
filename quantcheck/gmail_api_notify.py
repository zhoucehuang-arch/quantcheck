from __future__ import annotations

import base64
import mimetypes
import os
import smtplib
import ssl
import traceback
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))
LOG_FILE = ROOT / "logs" / "quantcheck_email.log"


def _log_failure(context: str, exc: Exception | str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        detail = str(exc)
        if isinstance(exc, Exception):
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{context}: {detail}\n")
    except Exception:
        pass


def parse_recipients(
    value: str | Iterable[str] | None,
    default: str | None = None,
    file_path: str | Path | None = None,
) -> List[str]:
    default = default or os.environ.get("NOTIFY_EMAIL_TO", "")
    if file_path is None:
        file_path = os.environ.get("NOTIFY_EMAIL_FILE", "")
    if value is None:
        raw_items = [default] if default else []
    elif isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    else:
        raw_items = []
        for item in value:
            raw_items.extend(str(item).replace(";", ",").split(","))
    if file_path:
        path = Path(file_path)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                body = line.split("#", 1)[0].strip()
                if body:
                    raw_items.extend(body.replace(";", ",").split(","))
    recipients: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        addr = item.strip()
        addr_key = addr.lower()
        if not addr or addr_key in seen:
            continue
        recipients.append(addr)
        seen.add(addr_key)
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
    except Exception as exc:
        _log_failure("smtp send failed", exc)
        return False


def send_via_gmail_api(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, timeout: int = 120, html: str | None = None) -> bool:
    """Send with Gmail API when google client libraries and OAuth token are configured.

    Required env/config:
      GMAIL_API_ENABLED=1
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
    except Exception as exc:
        _log_failure("gmail api send failed", exc)
        return False


def send_email(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, html: str | None = None) -> bool:
    return send_via_gmail_api(subject, body, to=to, attachments=attachments, html=html) or send_via_smtp(subject, body, to=to, attachments=attachments, html=html)
