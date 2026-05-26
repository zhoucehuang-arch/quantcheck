#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email
import hashlib
import html as html_lib
import imaplib
import json
import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses
from pathlib import Path
from typing import Iterable, List, Mapping

from quantcheck.config import load_env
from quantcheck.gmail_api_notify import send_email as deliver_email
from quantcheck.notify_routes import EmailRoute, recipients_for_route, route_label
from quantcheck.state import atomic_write_json

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))
STATE = ROOT / "state"
LOGS = ROOT / "logs"
LOG_FILE = LOGS / "official_mail_forwarder.log"
STATE_FILE = STATE / "official_mail_forwarder_state.json"

DEFAULT_SENDER_PATTERNS = ["@quantgt.io", "quant gt", "quantgt"]
DEFAULT_SUBJECT_PATTERNS = ["quant gt", "quantgt", "picks", "holdings", "portfolio"]

STATE.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class OfficialMail:
    uid: str
    subject: str
    from_header: str
    date: str
    text: str
    html: str


def log(message: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now(timezone.utc).isoformat()}] {message}\n")


def split_patterns(value: str | None, defaults: Iterable[str]) -> List[str]:
    raw = value if value is not None else ",".join(defaults)
    return [item.strip().lower() for item in re.split(r"[,;\n]+", raw or "") if item.strip()]


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for payload, charset in parts:
        if isinstance(payload, bytes):
            out.append(payload.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(payload)
    return "".join(out).strip()


def plain_text_from_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\s+", " ", text)).strip()


def extract_bodies(message: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            raw = part.get_payload()
            text = raw if isinstance(raw, str) else ""
        else:
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if content_type == "text/html":
            html_parts.append(text)
        else:
            plain_parts.append(text)
    html = "\n".join(html_parts).strip()
    text = "\n".join(plain_parts).strip()
    if not text and html:
        text = plain_text_from_html(html)
    return text, html


def official_mail_from_message(uid: str, raw_message: bytes) -> OfficialMail:
    msg = email.message_from_bytes(raw_message)
    text, html = extract_bodies(msg)
    return OfficialMail(
        uid=uid,
        subject=decode_header_value(msg.get("Subject")),
        from_header=decode_header_value(msg.get("From")),
        date=decode_header_value(msg.get("Date")),
        text=text,
        html=html,
    )


def address_text(from_header: str) -> str:
    addresses = getaddresses([from_header])
    if not addresses:
        return from_header.lower()
    return " ".join(f"{name} {addr}" for name, addr in addresses).lower()


def matches_official_mail(mail: OfficialMail, sender_patterns: Iterable[str], subject_patterns: Iterable[str]) -> bool:
    # Manual mailbox forwarding can rewrite the visible From header. Match
    # against the parsed sender plus the forwarded header/body context.
    source_text = " ".join([address_text(mail.from_header), mail.text[:4000], mail.html[:4000]]).lower()
    subject_text = " ".join([mail.subject, mail.text[:1000], mail.html[:1000]]).lower()
    sender_ok = any(pattern in source_text for pattern in sender_patterns)
    subject_ok = any(pattern in subject_text for pattern in subject_patterns)
    return sender_ok and subject_ok


def mail_fingerprint(mail: OfficialMail) -> str:
    payload = "\n".join([mail.from_header, mail.subject, mail.date, mail.text[:2000], mail.html[:2000]])
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"forwarded": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"forwarded": []}


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["forwarded"] = list(state.get("forwarded") or [])[-500:]
    state["history"] = list(state.get("history") or [])[-200:]
    atomic_write_json(STATE_FILE, state)


def build_forward_body(mail: OfficialMail) -> tuple[str, str, str | None]:
    subject = f"Quant GT Official Email: {mail.subject or '(no subject)'}"
    body = "\n".join([
        "Forwarded official Quant GT email.",
        f"From: {mail.from_header}",
        f"Date: {mail.date or 'Unknown'}",
        f"Subject: {mail.subject or '(no subject)'}",
        "",
        mail.text or "(No plain-text body was available.)",
    ])
    html = None
    if mail.html:
        html = f"""
        <div style="font-family:Arial,sans-serif;color:#111827">
          <p><strong>Forwarded official Quant GT email.</strong></p>
          <p><strong>From:</strong> {html_lib.escape(mail.from_header)}<br>
             <strong>Date:</strong> {html_lib.escape(mail.date or 'Unknown')}<br>
             <strong>Subject:</strong> {html_lib.escape(mail.subject or '(no subject)')}</p>
          <hr>
          {mail.html}
        </div>
        """
    return subject, body, html


def send_admin_alert(env: Mapping[str, str], subject: str, body: str) -> bool:
    recipients = recipients_for_route(EmailRoute.ADMIN, env)
    if not recipients:
        log(f"admin alert skipped: {route_label(EmailRoute.ADMIN)} not configured for {subject}")
        return False
    sent = deliver_email(subject, body, to=recipients)
    if sent:
        log(f"admin alert sent to {', '.join(recipients)}: {subject}")
    else:
        log(f"admin alert send failed: {subject}")
    return sent


def alert_forward_failures(env: Mapping[str, str], result: Mapping[str, object]) -> bool:
    failed = int(result.get("failed") or 0)
    if failed <= 0:
        return False
    body = "\n".join([
        "Official Quant GT email was detected, but redistribution failed.",
        f"Checked: {result.get('checked', 0)}",
        f"Matched: {result.get('matched', 0)}",
        f"Forwarded: {result.get('forwarded', 0)}",
        f"Failed: {failed}",
        "",
        f"Log: {LOG_FILE}",
    ])
    return send_admin_alert(env, "Quant GT Official Mail Forward Failed", body)


def connect_imap(env: Mapping[str, str]):
    host = env.get("OFFICIAL_MAIL_IMAP_HOST") or env.get("IMAP_HOST")
    username = env.get("OFFICIAL_MAIL_IMAP_USERNAME") or env.get("IMAP_USERNAME")
    password = env.get("OFFICIAL_MAIL_IMAP_PASSWORD") or env.get("IMAP_PASSWORD")
    port = int(env.get("OFFICIAL_MAIL_IMAP_PORT") or env.get("IMAP_PORT") or "993")
    if not (host and username and password):
        raise RuntimeError("missing OFFICIAL_MAIL_IMAP_HOST/OFFICIAL_MAIL_IMAP_USERNAME/OFFICIAL_MAIL_IMAP_PASSWORD")
    client = imaplib.IMAP4_SSL(host, port)
    client.login(username, password)
    return client


def search_uids(client, mailbox: str, query: str) -> list[str]:
    status, _ = client.select(mailbox, readonly=True)
    if status != "OK":
        raise RuntimeError(f"cannot select mailbox: {mailbox}")
    status, data = client.uid("search", None, query)
    if status != "OK":
        raise RuntimeError(f"imap search failed: {query}")
    return [uid.decode("ascii") for uid in (data[0] or b"").split()]


def fetch_message(client, uid: str) -> bytes:
    status, data = client.uid("fetch", uid, "(RFC822)")
    if status != "OK" or not data:
        raise RuntimeError(f"imap fetch failed for uid {uid}")
    for item in data:
        if isinstance(item, tuple) and item[1]:
            return item[1]
    raise RuntimeError(f"imap fetch returned no message body for uid {uid}")


def search_query(env: Mapping[str, str]) -> str:
    return env.get("OFFICIAL_MAIL_IMAP_SEARCH") or "UNSEEN"


def forward_official_mail(env: Mapping[str, str], *, dry_run: bool = False) -> dict:
    if env.get("OFFICIAL_MAIL_ENABLED", "0") != "1":
        log("official mail forward skipped: OFFICIAL_MAIL_ENABLED is not 1")
        return {"checked": 0, "matched": 0, "forwarded": 0, "skipped": "disabled"}

    recipients = recipients_for_route(EmailRoute.PICKS_UPDATE, env)
    if not recipients:
        log(f"mail forward skipped: {route_label(EmailRoute.PICKS_UPDATE)} not configured")
        return {"checked": 0, "matched": 0, "forwarded": 0, "skipped": "no_recipients"}

    sender_patterns = split_patterns(env.get("OFFICIAL_MAIL_SENDER_PATTERNS"), DEFAULT_SENDER_PATTERNS)
    subject_patterns = split_patterns(env.get("OFFICIAL_MAIL_SUBJECT_PATTERNS"), DEFAULT_SUBJECT_PATTERNS)
    mailbox = env.get("OFFICIAL_MAIL_IMAP_MAILBOX") or "INBOX"
    max_messages = int(env.get("OFFICIAL_MAIL_MAX_MESSAGES") or "20")
    state = load_state()
    forwarded = set(state.get("forwarded") or [])
    result = {"checked": 0, "matched": 0, "forwarded": 0, "failed": 0, "dry_run": dry_run}

    client = connect_imap(env)
    try:
        uids = search_uids(client, mailbox, search_query(env))[-max_messages:]
        for uid in uids:
            result["checked"] += 1
            mail = official_mail_from_message(uid, fetch_message(client, uid))
            if not matches_official_mail(mail, sender_patterns, subject_patterns):
                continue
            result["matched"] += 1
            fingerprint = mail_fingerprint(mail)
            if fingerprint in forwarded:
                continue
            subject, body, html = build_forward_body(mail)
            if not dry_run:
                sent = deliver_email(subject, body, to=recipients, html=html)
                if not sent:
                    result["failed"] += 1
                    log(f"official mail send failed uid={uid} subject={mail.subject!r}")
                    continue
                forwarded.add(fingerprint)
                state.setdefault("history", []).append({
                    "uid": uid,
                    "subject": mail.subject,
                    "from": mail.from_header,
                    "date": mail.date,
                    "fingerprint": fingerprint,
                    "forwarded_at": datetime.now(timezone.utc).isoformat(),
                })
            result["forwarded"] += 1
            log(f"forwarded official mail uid={uid} subject={mail.subject!r} to={', '.join(recipients)}")
        state["forwarded"] = sorted(forwarded)
        if not dry_run and result["forwarded"] > 0:
            save_state(state)
        return result
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="check and match messages without sending")
    args = parser.parse_args()
    load_env(ROOT)
    env = dict(os.environ)
    try:
        result = forward_official_mail(env, dry_run=args.dry_run)
        if not args.dry_run:
            alert_forward_failures(env, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        tb = traceback.format_exc()
        log(f"official mail forward failed: {exc}\n{tb}")
        if env.get("OFFICIAL_MAIL_ENABLED", "0") == "1":
            send_admin_alert(
                env,
                "Quant GT Official Mail Check Failed",
                f"Error: {exc}\n\n{tb[-3000:]}",
            )
        raise


if __name__ == "__main__":
    main()
