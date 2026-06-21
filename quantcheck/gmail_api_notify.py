from __future__ import annotations

import base64
import fcntl
import json
import mimetypes
import os
import re
import smtplib
import ssl
import tempfile
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))
LOG_FILE = ROOT / "logs" / "quantcheck_email.log"
LEDGER_FILE = ROOT / "logs" / "email_delivery_ledger.jsonl"


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


def _log_line(message: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def _ledger_record(provider: str, subject: str, recipient: str, success: bool, *, message_id: str | None = None, error: Exception | str | None = None) -> None:
    try:
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        error_text = None
        if error is not None:
            if isinstance(error, Exception):
                error_text = f"{type(error).__name__}: {error}"
            else:
                error_text = str(error)
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "recipient": recipient,
            "to": recipient,
            "subject": subject,
            "success": success,
            "status": "sent" if success else "failed",
        }
        if message_id:
            record["message_id"] = message_id
        if error_text:
            record["error"] = error_text[:1000]
        with LEDGER_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
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


def _token_lock_path(token_path: Path) -> Path:
    return token_path.with_name(token_path.name + ".lock")


def _atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    try:
        path.chmod(mode)
    except Exception:
        pass


def refresh_gmail_credentials(token_path: Path, scopes: list[str]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    lock_path = _token_lock_path(token_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds.expired and creds.refresh_token:
            old_text = token_path.read_text(encoding="utf-8") if token_path.exists() else ""
            creds.refresh(Request())
            refreshed = creds.to_json()
            if refreshed != old_text:
                backup_dir = token_path.parent / "backup"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_path = backup_dir / f"{token_path.stem}.pre_refresh.{stamp}.json"
                _atomic_write_text(backup_path, old_text or refreshed)
                _atomic_write_text(token_path, refreshed)
        return creds


def send_via_brevo_api(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, timeout: int = 60, html: str | None = None) -> bool:
    recipients = parse_recipients(to) if to is None else parse_recipients(to, file_path="")
    sender = os.environ.get("BREVO_FROM") or os.environ.get("SMTP_FROM")
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not (recipients and sender and api_key):
        return False
    try:
        payload: dict[str, object] = {
            "sender": {"name": sender.split("<", 1)[0].strip() if "<" in sender else sender, "email": sender.split("<", 1)[1].rstrip("> ") if "<" in sender and ">" in sender else sender},
            "to": [{"email": recipient} for recipient in recipients],
            "subject": subject,
            "textContent": body or "",
        }
        if html:
            payload["htmlContent"] = html
        brevo_attachments = []
        for attachment in attachments or []:
            path = Path(attachment)
            if not path.exists() or not path.is_file():
                continue
            brevo_attachments.append({"name": path.name, "content": base64.b64encode(path.read_bytes()).decode("ascii")})
        if brevo_attachments:
            payload["attachment"] = brevo_attachments
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=data,
            method="POST",
            headers={
                "api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            try:
                response_json = json.loads(response_body)
            except Exception:
                response_json = {}
            os.environ["QUANTCHECK_LAST_EMAIL_MESSAGE_ID"] = str(response_json.get("messageId") or "")
        return True
    except Exception as exc:
        _log_failure("brevo api send failed", exc)
        return False


def send_via_smtp(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, timeout: int = 30, html: str | None = None) -> bool:
    recipients = parse_recipients(to) if to is None else parse_recipients(to, file_path="")
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
    """Legacy Gmail API sender.

    Production delivery uses Brevo. This helper stays disabled unless
    GMAIL_API_ENABLED=1 is explicitly set for manual recovery.
    """
    if os.environ.get("GMAIL_API_ENABLED", "0") != "1":
        return False
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except Exception:
        return False
    recipients = parse_recipients(to) if to is None else parse_recipients(to, file_path="")
    sender = os.environ.get("GMAIL_API_FROM") or os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME")
    token_path = Path(os.environ.get("GMAIL_API_TOKEN", ROOT / ".config" / "gmail-api" / "token.json"))
    if not (recipients and sender and token_path.exists()):
        return False
    base_scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
    raw_scopes = os.environ.get("GMAIL_API_SCOPES") or os.environ.get("OFFICIAL_MAIL_GMAIL_SCOPES")
    scopes = list(base_scopes)
    if raw_scopes:
        for item in re.split(r"[,;\s]+", raw_scopes):
            item = item.strip()
            if item and item not in scopes:
                scopes.append(item)
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds.expired and creds.refresh_token:
            creds = refresh_gmail_credentials(token_path, scopes)
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


def _send_once(subject: str, body: str, recipient: str, attachments: list[Path], html: str | None) -> tuple[bool, str]:
    provider = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower()
    if provider == "brevo":
        return send_via_brevo_api(subject, body, to=[recipient], attachments=attachments, html=html), "brevo"
    if provider == "smtp":
        return send_via_smtp(subject, body, to=[recipient], attachments=attachments, html=html), "smtp"
    if provider == "gmail":
        return send_via_gmail_api(subject, body, to=[recipient], attachments=attachments, html=html), "gmail"
    if send_via_brevo_api(subject, body, to=[recipient], attachments=attachments, html=html):
        return True, "brevo"
    if send_via_smtp(subject, body, to=[recipient], attachments=attachments, html=html):
        return True, "smtp"
    if send_via_gmail_api(subject, body, to=[recipient], attachments=attachments, html=html):
        return True, "gmail"
    return False, "auto"


def send_email_per_recipient(
    subject: str,
    body: str,
    to: str | Iterable[str] | None = None,
    attachments: Iterable[Path] | None = None,
    html: str | None = None,
    retries: int = 1,
) -> tuple[List[str], List[str]]:
    """Send one private message per recipient, retrying failures so a single bad
    address never silently drops a subscriber. Returns (delivered, failed)."""
    recipients = parse_recipients(to) if to is None else parse_recipients(to, file_path="")
    attachments = list(attachments or [])
    delivered: list[str] = []
    failed: list[str] = []
    for recipient in recipients:
        sent = False
        provider_used = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower() or "auto"
        for _ in range(max(1, retries + 1)):
            sent, provider_used = _send_once(subject, body, recipient, attachments, html)
            if sent:
                break
        message_id = os.environ.pop("QUANTCHECK_LAST_EMAIL_MESSAGE_ID", "") if sent else ""
        _ledger_record(provider_used, subject, recipient, sent, message_id=message_id or None)
        (delivered if sent else failed).append(recipient)
    if failed:
        _log_line(f"per-recipient delivery FAILED for {len(failed)} recipient(s): {', '.join(failed)}: {subject}")
    return delivered, failed


def send_email(subject: str, body: str, to: str | Iterable[str] | None = None, attachments: Iterable[Path] | None = None, html: str | None = None) -> bool:
    """Send one private message per recipient so subscribers never see each other."""
    delivered, failed = send_email_per_recipient(subject, body, to=to, attachments=attachments, html=html)
    return bool(delivered) and not failed
