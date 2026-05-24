#!/usr/bin/env python3
"""
Quant GT pick monitor.

Modes:
  --mode baseline  Fetch current data and initialize state without notification.
  --mode check     Trading-window aware check; notify only on data change/failure.
  --mode fetch     Fetch current data and print summary.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Reuse the existing fetch/export implementation so Excel formatting stays in one place.
from quantcheck.config import load_env as load_dotenv
from quantcheck.diff import compare
from quantcheck import picks_report as report
from quantcheck.gmail_api_notify import parse_recipients, send_email as deliver_email
from quantcheck.notify_dedupe import should_send_notification
from quantcheck.state import atomic_write_json, prune_old_files as prune_files
from quantcheck.validation import validate_member_picks_data

ROOT = Path(os.environ.get('QUANTCHECK_HOME', Path(__file__).resolve().parents[1]))
STATE = ROOT / 'state'
OUTPUT = ROOT / 'output'
SHOTS = ROOT / 'screenshots'
LOGS = ROOT / 'logs'
PROFILE = ROOT / 'browser-profile'
LATEST = STATE / 'latest_picks.json'
PREVIOUS = STATE / 'previous_picks.json'
HEALTH = STATE / 'health.json'
LAST_CHANGE_NOTIFICATION = STATE / 'last_picks_change_notification.json'
LOG_FILE = LOGS / 'quantgt_monitor.log'
BASE = 'https://quantgt.io'
NY = ZoneInfo('America/New_York')
WINDOWS = {
    'premarket_0830': (8, 30),
    'premarket_0900': (9, 0),
    'open_0940': (9, 40),
    'postmarket_1700': (17, 0),
}

for d in [STATE, OUTPUT, SHOTS, LOGS, PROFILE]:
    d.mkdir(parents=True, exist_ok=True)


def load_env() -> Dict[str, str]:
    return load_dotenv(ROOT)


def log(msg: str, echo: bool = False):
    ts = datetime.now(timezone.utc).isoformat()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] {msg}\n')
    if echo:
        print(msg)


def json_dump(path: Path, obj: Any):
    atomic_write_json(path, obj)


def json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def trading_day(dt_ny: datetime) -> bool:
    cal = mcal.get_calendar('NYSE')
    start = dt_ny.date().isoformat()
    sched = cal.schedule(start_date=start, end_date=start)
    return not sched.empty


def current_window(dt_ny: datetime, tolerance_minutes: int = 20) -> str | None:
    for name, (h, m) in WINDOWS.items():
        target = dt_ny.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((dt_ny - target).total_seconds()) <= tolerance_minutes * 60:
            return name
    return None


def strip_dynamic(data: Dict[str, Any]) -> Dict[str, Any]:
    d = copy.deepcopy(data)
    d.pop('fetched_at', None)
    return d


def format_row_brief(row: Dict[str, Any], fields: List[str]) -> str:
    parts = []
    for field in fields:
        value = row.get(field)
        if value not in (None, ''):
            label = field.replace('_', ' ').title()
            parts.append(f'{label}: {value}')
    return '; '.join(parts)


def format_pick_list(title: str, section: Dict[str, Any], max_rows: int = 12) -> List[str]:
    rows = section.get('rows', []) or []
    lines = [f"{title}: {section.get('pick_date', 'Unknown')} · {len(rows)} stocks"]
    if not rows:
        lines.append('- None captured')
        return lines
    for idx, row in enumerate(rows[:max_rows], 1):
        if title.startswith('Monthly'):
            meta = format_row_brief(row, ['return', 'rating', 'gt_score', 'current_price', 'buy_or_entry_price'])
        else:
            meta = format_row_brief(row, ['rating', 'gt_score', 'current_price', 'buy_or_entry_price', 'analyst_signal'])
        symbol = row.get('symbol') or '?'
        company = row.get('company') or ''
        lines.append(f"{idx}. {symbol} — {company}" + (f" | {meta}" if meta else ''))
    if len(rows) > max_rows:
        lines.append(f'- ... {len(rows) - max_rows} more stocks in attached Excel')
    return lines


def build_notification_html(data: Dict[str, Any], diff: Dict[str, Any] | None = None, context: str = 'change') -> str:
    def esc(v: Any) -> str:
        return html.escape(str(v or ''))

    def table(section_name: str, section: Dict[str, Any], mode: str) -> str:
        rows = section.get('rows', []) or []
        if mode == 'monthly':
            cols = [
                ('symbol', 'Symbol'), ('company', 'Company'), ('return', 'Return'), ('rating', 'Rating'),
                ('gt_score', 'GT Score'), ('current_price', 'Price'), ('buy_or_entry_price', 'Entry'), ('next_earnings', 'Earnings')
            ]
        else:
            cols = [
                ('symbol', 'Symbol'), ('company', 'Company'), ('sector', 'Sector'), ('rating', 'Rating'),
                ('gt_score', 'GT Score'), ('current_price', 'Price'), ('buy_or_entry_price', 'Buy'), ('analyst_signal', 'Signal')
            ]
        header = ''.join(f'<th style="{TH}">{esc(label)}</th>' for _, label in cols)
        body = []
        for idx, row in enumerate(rows, 1):
            tds = []
            for key, _ in cols:
                val = row.get(key, '')
                style = TD
                sval = str(val or '')
                if key == 'symbol':
                    style += 'font-weight:700;color:#16a34a;white-space:nowrap;'
                elif key in {'return', 'gt_score'}:
                    style += 'text-align:center;font-weight:700;'
                    if sval.startswith('+'):
                        style += 'color:#16a34a;'
                    elif sval.startswith('-'):
                        style += 'color:#dc2626;'
                elif key in {'current_price', 'buy_or_entry_price'}:
                    style += 'text-align:right;white-space:nowrap;'
                elif key in {'rating', 'analyst_signal'}:
                    style += 'text-align:center;white-space:nowrap;'
                tds.append(f'<td style="{style}">{esc(val)}</td>')
            body.append(f'<tr>{"".join(tds)}</tr>')
        if not body:
            body.append(f'<tr><td colspan="{len(cols)}" style="{TD}">No rows captured</td></tr>')
        return f'''
        <section style="margin:20px 0 0 0;">
          <h2 style="font-size:18px;line-height:1.3;color:#0f172a;margin:0 0 6px 0;">{esc(section_name)}</h2>
          <div style="font-size:15px;color:#64748b;margin:0 0 10px 0;">Date: {esc(section.get('pick_date', 'Unknown'))} · {len(rows)} stocks</div>
          <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #d7e3da;border-radius:12px;background:#ffffff;">
            <table role="presentation" cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;min-width:980px;font-size:15px;line-height:1.4;">
              <thead><tr>{header}</tr></thead>
              <tbody>{''.join(body)}</tbody>
            </table>
          </div>
        </section>'''

    def change_box(diff_obj: Dict[str, Any] | None) -> str:
        if diff_obj is None:
            return ''
        summary = summarize_diff(diff_obj)
        items = ''.join(f'<li style="margin:3px 0;">{esc(line.lstrip("- "))}</li>' for line in summary.splitlines() if line.strip())
        return f'''
        <section style="margin:18px 0 0 0;background:#f8fafc;border:1px solid #d7e3da;border-radius:12px;padding:14px 16px;">
          <h2 style="font-size:16px;color:#0f172a;margin:0 0 8px 0;">Changes</h2>
          <ul style="padding-left:18px;margin:0;color:#334155;font-size:13px;line-height:1.5;">{items}</ul>
        </section>'''

    monthly = data.get('monthly', {})
    weekly = data.get('weekly', {})
    fetched = data.get('fetched_at') or now_utc()
    TH = 'background:#dcfce7;color:#0f7a36;border-bottom:2px solid #16a34a;padding:12px 13px;text-align:left;font-size:14px;white-space:nowrap;'
    TD = 'border-bottom:1px solid #d7e3da;padding:12px 13px;color:#0f172a;vertical-align:middle;background:#ffffff;'
    return f'''<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f8f7;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
    <div style="max-width:1180px;margin:0 auto;padding:14px 8px;">
      <div style="background:#ffffff;border:1px solid #d7e3da;border-radius:16px;padding:18px 14px;">
        <div style="font-size:12px;color:#16a34a;font-weight:700;letter-spacing:.06em;text-transform:uppercase;">Quant GT Monitor</div>
        <h1 style="font-size:26px;line-height:1.2;margin:6px 0 8px 0;color:#0f172a;">Picks Report</h1>
        <div style="font-size:13px;color:#64748b;line-height:1.5;">Context: {esc(context)}<br>Fetched: {esc(fetched)}<br>Source: {esc(data.get('source', BASE))}</div>
        {change_box(diff)}
        {table('Monthly Picks', monthly, 'monthly')}
        {table('Weekly Picks', weekly, 'weekly')}
      </div>
    </div>
  </body>
</html>'''


def build_notification_body(data: Dict[str, Any], diff: Dict[str, Any] | None = None, context: str = 'change') -> str:
    fetched = data.get('fetched_at') or now_utc()
    monthly = data.get('monthly', {})
    weekly = data.get('weekly', {})
    lines = [
        'Quant GT Picks Monitor',
        f'Context: {context}',
        f'Fetched: {fetched}',
        f"Source: {data.get('source', BASE)}",
    ]
    if diff is not None:
        lines += ['', 'Changes:', summarize_diff(diff)]
    lines += [
        '',
        'Current Picks:',
        *format_pick_list('Monthly Picks', monthly),
        '',
        *format_pick_list('Weekly Picks', weekly),
    ]
    return '\n'.join(lines)


def build_telegram_body(data: Dict[str, Any], diff: Dict[str, Any] | None = None, context: str = 'change') -> str:
    monthly = data.get('monthly', {})
    weekly = data.get('weekly', {})
    fetched = data.get('fetched_at') or now_utc()
    lines = [
        'Quant GT Monitor',
        f'Context: {context}',
        f'Fetched: {fetched}',
        '',
        'Summary:',
        f"- Monthly Picks: {monthly.get('pick_date', 'Unknown')} · {len(monthly.get('rows', []) or [])} stocks",
        f"- Weekly Picks: {weekly.get('pick_date', 'Unknown')} · {len(weekly.get('rows', []) or [])} stocks",
    ]
    if diff is not None:
        summary = summarize_diff(diff, compact=True)
        lines += ['', 'Changes:', summary]
    else:
        lines += ['', 'Changes: not evaluated in this manual test']
    lines += ['', 'See attached Excel and screenshots for details.']
    return '\n'.join(lines)


def summarize_diff(diff: Dict[str, Any], compact: bool = False) -> str:
    lines = []
    for section, title in [('monthly', 'Monthly Picks'), ('weekly', 'Weekly Picks')]:
        d = diff.get(section, {})
        if not d.get('changed_flag'):
            continue
        if compact:
            bits = []
            if d.get('date'):
                bits.append('date')
            if d.get('added'):
                bits.append(f"+{len(d['added'])}")
            if d.get('removed'):
                bits.append(f"-{len(d['removed'])}")
            if d.get('changed'):
                bits.append(f"{len(d['changed'])} rows changed")
            lines.append(f"- {title}: " + (', '.join(bits) if bits else 'changed'))
            continue
        lines.append(f'{title} changed')
        if d.get('date'):
            lines.append(f"- Date: {d['date']['old']} -> {d['date']['new']}")
        if d.get('added'):
            lines.append('- Added: ' + ', '.join(d['added']))
        if d.get('removed'):
            lines.append('- Removed: ' + ', '.join(d['removed']))
        for item in d.get('changed', [])[:12]:
            field_bits = []
            for field, vals in list(item['fields'].items())[:5]:
                field_bits.append(f"{field}: {vals['old']} -> {vals['new']}")
            lines.append(f"- {item['symbol']}: " + '; '.join(field_bits))
        if len(d.get('changed', [])) > 12:
            lines.append(f"- ... {len(d['changed']) - 12} more changed rows")
    return '\n'.join(lines) if lines else 'No changes.'


def send_telegram(text: str, media: List[Path] | None = None):
    msg = text
    for p in media or []:
        if p and p.exists():
            msg += f"\nMEDIA:{p}"
    # Standalone email-only mode; no platform-specific delivery is required.
    return


def send_email(subject: str, body: str, attachments: List[Path] | None = None, html_body: str | None = None):
    env = load_env()
    recipients = parse_recipients(env.get('NOTIFY_EMAIL_TO'), file_path=env.get('NOTIFY_EMAIL_FILE'))
    if not recipients:
        log(f'email skipped: NOTIFY_EMAIL_TO is not configured for {subject}')
        return
    if deliver_email(subject, body, to=recipients, attachments=attachments or [], html=html_body):
        log(f'email sent to {", ".join(recipients)}: {subject}')
    else:
        log(f'email send failed or no sender configured: {subject}')


def notify(subject: str, body: str, media: List[Path] | None = None, html_body: str | None = None, telegram_body: str | None = None):
    # Standalone mode sends email directly and records a local notification marker.
    # The script stays quiet on no-change runs; change/test runs print a concise
    # summary so service logs remain auditable.
    send_email(subject, body, media, html_body=html_body)
    tg = telegram_body or body
    note = {'subject': subject, 'body': tg, 'email_body': body, 'media': [str(p) for p in media or [] if p.exists()], 'at': now_utc()}
    json_dump(STATE / 'last_notification.json', note)
    print('\n'.join([subject, tg] + [f'ATTACHMENT:{p}' for p in media or [] if p.exists()]))


def ensure_login(page, env: Dict[str, str]):
    page.goto(f'{BASE}/dashboard/quantgt-picks', wait_until='domcontentloaded', timeout=45000)
    try:
        page.wait_for_load_state('load', timeout=15000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2500)
    if report.has_picks_content(page) and report.has_auth_session(page) and not report.is_login_prompt_visible(page):
        return
    email = env.get('QUANTGT_EMAIL')
    password = env.get('QUANTGT_PASSWORD')
    if not email or not password:
        raise RuntimeError('Missing QUANTGT_EMAIL/QUANTGT_PASSWORD in .env')
    page.goto(f'{BASE}/login?redirect=/dashboard/quantgt-picks', wait_until='domcontentloaded', timeout=45000)
    try:
        page.wait_for_load_state('load', timeout=15000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1000)
    if page.get_by_role('button', name=re.compile('log in', re.I)).count() > 0:
        page.get_by_role('button', name=re.compile('log in', re.I)).click()
    email_box = page.get_by_placeholder('you@example.com') if page.get_by_placeholder('you@example.com').count() else page.locator('input[type="email"]')
    pass_box = page.get_by_placeholder('min. 8 characters') if page.get_by_placeholder('min. 8 characters').count() else page.locator('input[type="password"]')
    email_box.fill(email)
    pass_box.fill(password)
    page.get_by_role('button', name=re.compile('log in|sign in', re.I)).click()
    try:
        page.wait_for_load_state('domcontentloaded', timeout=20000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(3000)
    page.goto(f'{BASE}/dashboard/quantgt-picks', wait_until='domcontentloaded', timeout=45000)
    try:
        page.wait_for_load_state('load', timeout=15000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2500)
    report.wait_for_picks_content(page)
    report.assert_authenticated_page(page, 'monthly')


def capture_logged_in_screenshots(which: List[str]) -> Dict[str, Path]:
    env = load_env()
    ts = datetime.now(NY).strftime('%Y-%m-%d_%H%M%S')
    out = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True, viewport={'width': 1440, 'height': 1100})
        page = ctx.new_page()
        ensure_login(page, env)
        targets = {
            'monthly': f'{BASE}/dashboard/quantgt-picks',
            'weekly': f'{BASE}/dashboard/weekly-picks',
        }
        for name in which:
            page.goto(targets[name], wait_until='domcontentloaded', timeout=45000)
            try:
                page.wait_for_load_state('load', timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(3000)
            report.wait_for_picks_content(page)
            report.assert_authenticated_page(page, name)
            path = SHOTS / f'{name}_picks_{ts}.png'
            page.screenshot(path=str(path), full_page=True)
            out[name] = path
        ctx.close()
    return out


def prune_old_files(directory: Path, pattern: str, keep: int = 200):
    prune_files(directory, pattern, keep)


def fetch_current() -> Dict[str, Any]:
    env = load_env()
    os.environ.setdefault('QUANTGT_EMAIL', env.get('QUANTGT_EMAIL', ''))
    os.environ.setdefault('QUANTGT_PASSWORD', env.get('QUANTGT_PASSWORD', ''))
    report.EMAIL = os.environ.get('QUANTGT_EMAIL', '')
    report.PASSWORD = os.environ.get('QUANTGT_PASSWORD', '')
    data = report.fetch()
    validate_member_picks_data(data)
    if str(data.get('monthly', {}).get('pick_date') or '') == 'Unknown':
        log('warning: monthly pick date parsed as Unknown; date-only diff will be ignored')
    data['auth_verified'] = True
    data['source_policy'] = 'logged-in member page only; unauthenticated/demo data rejected'
    return data


def write_health(**kwargs):
    old = {}
    if HEALTH.exists():
        try:
            old = json_load(HEALTH)
        except Exception:
            old = {}
    obj = {**old, **kwargs, 'updated_at': now_utc()}
    json_dump(HEALTH, obj)


def run_baseline(echo: bool = True):
    data = fetch_current()
    if LATEST.exists():
        PREVIOUS.write_text(LATEST.read_text(encoding='utf-8'), encoding='utf-8')
    json_dump(LATEST, data)
    # Preserve compatibility for old scripts.
    json_dump(ROOT / 'latest_picks.json', data)
    write_health(last_run_at=now_utc(), last_success_at=now_utc(), last_error=None, consecutive_failures=0,
                 monthly_date=data['monthly']['pick_date'], weekly_date=data['weekly']['pick_date'], mode='baseline')
    log('baseline initialized', echo=echo)
    if echo:
        print(json.dumps({'status': 'baseline_initialized', 'monthly': data['monthly']['pick_date'], 'weekly': data['weekly']['pick_date']}, ensure_ascii=False, indent=2))


def run_check(force=False, no_random=False):
    env = load_env()
    dt_ny = datetime.now(NY)
    window = current_window(dt_ny)
    if not force:
        if not trading_day(dt_ny):
            log('skip: not NYSE trading day')
            return
        if not window:
            log(f'skip: outside target window at {dt_ny.isoformat()}')
            return
    if not no_random:
        delay = random.randint(0, 300)
        log(f'random delay {delay}s')
        time.sleep(delay)
    try:
        data = fetch_current()
        raw_dir = STATE / 'raw'
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"picks_raw_{datetime.now(NY).strftime('%Y-%m-%d_%H%M%S')}.json"
        json_dump(raw_path, data)
        prune_old_files(raw_dir, 'picks_raw_*.json', keep=240)
        old = json_load(LATEST) if LATEST.exists() else None
        if old is None:
            json_dump(LATEST, data)
            json_dump(ROOT / 'latest_picks.json', data)
            write_health(last_run_at=now_utc(), last_success_at=now_utc(), last_error=None, consecutive_failures=0, last_window=window or 'forced')
            log('initialized latest state, no notification')
            return
        diff = compare(strip_dynamic(old), strip_dynamic(data))
        write_health(last_run_at=now_utc(), last_success_at=now_utc(), last_error=None, consecutive_failures=0,
                     last_window=window or 'forced', monthly_date=data['monthly']['pick_date'], weekly_date=data['weekly']['pick_date'], changed=diff['changed'])
        if not diff['changed']:
            log('no pick changes')
            return
        if not should_send_notification(diff, data, dedupe_path=LAST_CHANGE_NOTIFICATION):
            write_health(last_run_at=now_utc(), last_success_at=now_utc(), last_error=None, consecutive_failures=0,
                         last_window=window or 'forced', monthly_date=data['monthly']['pick_date'], weekly_date=data['weekly']['pick_date'], changed=False,
                         duplicate_notification_suppressed=True)
            return
        PREVIOUS.write_text(LATEST.read_text(encoding='utf-8'), encoding='utf-8')
        json_dump(LATEST, data)
        json_dump(ROOT / 'latest_picks.json', data)
        excel = report.export_excel(data)
        prune_old_files(OUTPUT, 'quantgt_picks_report_*.xlsx', keep=80)
        changed_pages = []
        if diff['monthly'].get('changed_flag'):
            changed_pages.append('monthly')
        if diff['weekly'].get('changed_flag'):
            changed_pages.append('weekly')
        shots = capture_logged_in_screenshots(changed_pages)
        prune_old_files(SHOTS, '*_picks_*.png', keep=160)
        tg_body = build_telegram_body(data, diff, context=f'picks changed · window={window or "forced"}')
        body = build_notification_body(data, diff, context=f'picks changed · window={window or "forced"}')
        html_body = build_notification_html(data, diff, context=f'picks changed · window={window or "forced"}')
        media = [excel] + list(shots.values())
        notify('Quant GT Picks Updated', body, media, html_body=html_body, telegram_body=tg_body)
    except Exception as e:
        tb = traceback.format_exc()
        log('check failed: ' + tb)
        health = json_load(HEALTH) if HEALTH.exists() else {}
        failures = int(health.get('consecutive_failures') or 0) + 1
        failure_shot = None
        try:
            # Best-effort screenshot of dashboard/login state.
            shots = capture_logged_in_screenshots(['weekly'])
            failure_shot = shots.get('weekly')
        except Exception:
            pass
        write_health(last_run_at=now_utc(), last_error=str(e), consecutive_failures=failures, last_window=window or 'forced')
        subject = 'Quant GT Monitor Failed' if failures < 3 else f'Quant GT Monitor Consecutive Failures ({failures})'
        body = f'Window: {window or "forced"}\nError: {e}\nConsecutive failures: {failures}\n\n{tb[-2000:]}'
        notify(subject, body, [failure_shot] if failure_shot else [])
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['baseline', 'check', 'fetch', 'screenshot'], default='check')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-random', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--test-email', action='store_true', help='Fetch current picks, export Excel, capture screenshots, and send a test email notification')
    args = ap.parse_args()
    if args.test_email:
        data = fetch_current()
        raw_dir = STATE / 'raw'
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"picks_raw_test_{datetime.now(NY).strftime('%Y-%m-%d_%H%M%S')}.json"
        json_dump(raw_path, data)
        excel = report.export_excel(data)
        shots = capture_logged_in_screenshots(['monthly', 'weekly'])
        tg_body = build_telegram_body(data, None, context='manual full-flow test')
        body = build_notification_body(data, None, context='manual full-flow test')
        html_body = build_notification_html(data, None, context='manual full-flow test')
        media = [excel] + list(shots.values())
        notify('Quant GT Monitor Test: Full Flow Report + Screenshots', body, media, html_body=html_body, telegram_body=tg_body)
        print(json.dumps({'status': 'test_notification_sent', 'excel': str(excel), 'raw': str(raw_path), 'screenshots': {k: str(v) for k, v in shots.items()}}, ensure_ascii=False, indent=2))
        return
    if args.mode == 'baseline':
        run_baseline(echo=not args.quiet)
    elif args.mode == 'fetch':
        data = fetch_current()
        print(json.dumps({'monthly': data['monthly']['pick_date'], 'weekly': data['weekly']['pick_date'], 'monthly_symbols': [r.get('symbol') for r in data['monthly']['rows']], 'weekly_symbols': [r.get('symbol') for r in data['weekly']['rows']]}, ensure_ascii=False, indent=2))
    elif args.mode == 'screenshot':
        shots = capture_logged_in_screenshots(['monthly', 'weekly'])
        print(json.dumps({k: str(v) for k, v in shots.items()}, ensure_ascii=False, indent=2))
    else:
        run_check(force=args.force, no_random=args.no_random)


if __name__ == '__main__':
    main()
