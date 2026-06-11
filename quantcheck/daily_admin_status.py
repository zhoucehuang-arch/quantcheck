from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quantcheck.config import load_env
from quantcheck.email_templates import build_card_email_html
from quantcheck.gmail_api_notify import refresh_gmail_credentials, send_email as deliver_email
from quantcheck.notify_routes import EmailRoute, recipients_for_route

ROOT = Path(os.environ.get("QUANTCHECK_HOME", Path(__file__).resolve().parents[1]))
STATE = ROOT / "state"
LOGS = ROOT / "logs"
LOG_FILE = LOGS / "daily_admin_status.log"
NY = ZoneInfo("America/New_York")


def log(message: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a", encoding="utf-8").write(f"[{datetime.now(timezone.utc).isoformat()}] {message}\n")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": str(exc)}


def gmail_token_status(env: dict[str, str]) -> tuple[str, str]:
    raw_path = env.get("GMAIL_API_TOKEN") or env.get("OFFICIAL_MAIL_GMAIL_TOKEN") or ""
    if not raw_path:
        return "missing", "not configured"
    token_path = Path(raw_path)
    if not token_path.exists():
        return "missing", str(token_path)
    scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
    try:
        creds = refresh_gmail_credentials(token_path, scopes)
        if creds.valid:
            return "valid", "Gmail API token refreshed/valid"
        return "invalid", f"expired={creds.expired} refresh_token={bool(creds.refresh_token)}"
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"


def build_status(env: dict[str, str]) -> tuple[str, str, str]:
    now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY)
    health = load_json(STATE / "health.json")
    official = load_json(STATE / "official_mail_forwarder_state.json")
    token_state, token_detail = gmail_token_status(env)
    recipients = recipients_for_route(EmailRoute.ADMIN, env)

    cards = [
        {"label": "NY Time", "value": now_ny.isoformat()},
        {"label": "UTC Time", "value": now_utc.isoformat()},
        {"label": "Admin Recipients", "value": len(recipients)},
        {
            "label": "Gmail API Token",
            "value": f"{token_state}: {token_detail}",
            "tone": "error" if token_state != "valid" else "neutral",
        },
        {
            "label": "Last Monitor Run",
            "value": health.get("last_run_at") or "missing",
            "tone": "warning" if not health.get("last_run_at") else "neutral",
        },
        {
            "label": "Last Monitor Success",
            "value": health.get("last_success_at") or "missing",
            "tone": "warning" if not health.get("last_success_at") else "neutral",
        },
        {
            "label": "Consecutive Failures",
            "value": health.get("consecutive_failures", 0),
            "tone": "error" if int(health.get("consecutive_failures") or 0) else "neutral",
        },
        {"label": "Last Window", "value": health.get("last_window") or "missing"},
        {
            "label": "Official Mail State",
            "value": json.dumps(official, ensure_ascii=True, sort_keys=True)[:1200] or "missing",
        },
    ]
    subject = f"Quant GT Daily Admin Status - {now_ny.strftime('%Y-%m-%d')}"
    body = "\n".join(f"{card['label']}: {card['value']}" for card in cards)
    html = build_card_email_html("Daily Admin Status", cards, context="daily admin heartbeat")
    return subject, body, html


def send_daily_status() -> bool:
    env = load_env(ROOT, override=True)
    recipients = recipients_for_route(EmailRoute.ADMIN, env)
    if not recipients:
        log("skipped: no admin recipients configured")
        return False
    subject, body, html = build_status(env)
    ok = deliver_email(subject, body, to=recipients, html=html)
    log(("sent" if ok else "failed") + f": {subject} admin_count={len(recipients)}")
    print(subject)
    print(body)
    return ok


def main() -> None:
    raise SystemExit(0 if send_daily_status() else 1)


if __name__ == "__main__":
    main()