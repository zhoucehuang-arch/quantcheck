#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from quantcheck.config import load_env
from quantcheck.gmail_api_notify import parse_recipients, send_email as deliver_email
from quantcheck.state import atomic_write_json

ROOT = Path(os.environ.get('QUANTCHECK_HOME', Path(__file__).resolve().parents[1]))
STATE = ROOT / 'state'
HEALTH = STATE / 'health.json'
LOGS = ROOT / 'logs'
LOG_FILE = LOGS / 'quantgt_health.log'
NY = ZoneInfo('America/New_York')
WINDOWS = {
    'premarket_0830': (8, 30),
    'premarket_0900': (9, 0),
    'open_0940': (9, 40),
    'postmarket_1700': (17, 0),
}
MAX_SUCCESS_AGE_TRADING_DAY_HOURS = 30
MAX_SUCCESS_AGE_CALENDAR_HOURS = 96

STATE.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    LOG_FILE.open('a', encoding='utf-8').write(f'[{datetime.now(timezone.utc).isoformat()}] {msg}\n')


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_json(path: Path, data: dict):
    atomic_write_json(path, data)


def parse_dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def is_trading_day(dt_ny: datetime) -> bool:
    cal = mcal.get_calendar('NYSE')
    sched = cal.schedule(start_date=dt_ny.date().isoformat(), end_date=dt_ny.date().isoformat())
    return not sched.empty


def expected_windows_passed(dt_ny: datetime):
    out = []
    for name, (h, m) in WINDOWS.items():
        if dt_ny >= dt_ny.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=25):
            out.append(name)
    return out


def send_email(subject: str, body: str):
    env = load_env(ROOT)
    recipients = parse_recipients(env.get('NOTIFY_EMAIL_TO'), file_path=env.get('NOTIFY_EMAIL_FILE'))
    if not recipients:
        log(f'email skipped: NOTIFY_EMAIL_TO is not configured for {subject}')
        return
    if deliver_email(subject, body, to=recipients):
        log(f'email sent to {", ".join(recipients)}: {subject}')
    else:
        log(f'email send failed or no sender configured: {subject}')


def notify(subject: str, body: str):
    send_email(subject, body)
    save_json(STATE / 'last_health_notification.json', {'subject': subject, 'body': body, 'at': datetime.now(timezone.utc).isoformat()})
    print(subject)
    print(body)


def check(force_alert=False):
    h = load_json(HEALTH)
    now = datetime.now(timezone.utc)
    now_ny = now.astimezone(NY)
    last_success = parse_dt(h.get('last_success_at'))
    last_run = parse_dt(h.get('last_run_at'))
    failures = int(h.get('consecutive_failures') or 0)
    problems = []

    if not HEALTH.exists():
        problems.append('health.json missing')
    if failures >= 2:
        problems.append(f'consecutive failures: {failures}')
    if not last_success:
        problems.append('last_success_at missing')
    else:
        age_h = (now - last_success.astimezone(timezone.utc)).total_seconds() / 3600
        if is_trading_day(now_ny):
            if expected_windows_passed(now_ny) and age_h > MAX_SUCCESS_AGE_TRADING_DAY_HOURS:
                problems.append(f'last success too old on trading day: {age_h:.1f}h')
        elif age_h > MAX_SUCCESS_AGE_CALENDAR_HOURS:
            problems.append(f'last success too old: {age_h:.1f}h')
    if force_alert:
        problems.append('forced health test alert')

    if problems:
        body = '\n'.join([
            'Quant GT Monitor Health Alert',
            f'NY time: {now_ny.isoformat()}',
            f'Last run: {h.get("last_run_at")}',
            f'Last success: {h.get("last_success_at")}',
            f'Last window: {h.get("last_window")}',
            f'Consecutive failures: {failures}',
            '',
            'Problems:',
            *[f'- {p}' for p in problems],
            '',
            'Last error:',
            str(h.get('last_error') or 'None')[:2000],
            '',
            'Action: check scraper login/selectors and recent cron logs if this is not a forced test.',
        ])
        notify('Quant GT Monitor Health Alert', body)
        log('alert: ' + '; '.join(problems))
    else:
        log('ok')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force-alert', action='store_true')
    args = ap.parse_args()
    check(force_alert=args.force_alert)

if __name__ == '__main__':
    main()
