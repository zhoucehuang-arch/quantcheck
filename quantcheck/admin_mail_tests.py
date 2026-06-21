from __future__ import annotations

import argparse
from datetime import datetime, timezone

from quantcheck.config import load_env
from quantcheck.notify_routes import EmailRoute, admin_recipients
from quantcheck.official_mail_forwarder import forward_official_mail
from quantcheck.picks_check import build_system_alert_html, load_env as load_picks_env, run_test_email, send_email

STRICT_OFFICIAL_QUERY = "in:anywhere newer_than:30d from:quantgt.io"


def _load_env() -> dict[str, str]:
    env = load_env()
    load_picks_env()
    env["OFFICIAL_MAIL_GMAIL_QUERY"] = STRICT_OFFICIAL_QUERY
    return env


def _send_admin_summary(title: str, lines: list[str]) -> None:
    env = _load_env()
    recipients = admin_recipients(env)
    if not recipients:
        raise RuntimeError("No admin recipients configured")
    html = build_system_alert_html(
        title,
        [{"label": f"Line {idx + 1}", "value": line} for idx, line in enumerate(lines)],
        context="admin mail tests",
    )
    body = "\n".join(lines)
    send_email(title, body, html_body=html, route=EmailRoute.ADMIN)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run official mail and picks test emails for admins")
    ap.add_argument("--dry-run", action="store_true", help="run the checks without sending the final admin summary")
    args = ap.parse_args()

    env = _load_env()
    started = datetime.now(timezone.utc).isoformat()
    summary: list[str] = [f"Started: {started}"]
    summary.append(f"Official Gmail query: {env['OFFICIAL_MAIL_GMAIL_QUERY']}")

    forward_result = forward_official_mail(env, dry_run=True, admin_only=True)
    summary.append(
        "Official mail forward: "
        f"checked={forward_result.get('checked', 0)} matched={forward_result.get('matched', 0)} "
        f"forwarded={forward_result.get('forwarded', 0)} failed={forward_result.get('failed', 0)} "
        f"provider={forward_result.get('provider', 'unknown')} admin_only={forward_result.get('admin_only', False)}"
    )

    try:
        run_test_email()
        summary.append("Picks test email: sent")
    except Exception as exc:
        summary.append(f"Picks test email: failed with {exc}")

    if args.dry_run:
        print("\n".join(summary))
        return

    _send_admin_summary("Quant GT Official Mail + Picks Test", summary)
    print("\n".join(summary))


if __name__ == "__main__":
    main()
