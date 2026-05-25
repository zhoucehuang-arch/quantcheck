#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from quantcheck.config import load_env
from quantcheck.gmail_api_notify import send_email as deliver_email
from quantcheck.notify_routes import EmailRoute, recipients_for_route
from quantcheck.state import atomic_write_json

ROOT = Path(os.environ.get('QUANTCHECK_HOME', Path(__file__).resolve().parents[1]))
STATE = ROOT / 'state'
LATEST = STATE / 'site_snapshot_latest.json'
PREVIOUS = STATE / 'site_snapshot_previous.json'
LAST_NOTE = STATE / 'last_site_update_notification.json'

IGNORE_KEYS = {'captured_at', 'screenshots'}
PAGE_ERROR_MARKERS = (
    'Timeout',
    'Page.goto',
    'net::',
    'Navigation',
    'Target closed',
)


def is_capture_error_page(page: dict | None) -> bool:
    if not isinstance(page, dict):
        return True
    err = str(page.get('error') or '').strip()
    if err:
        return True
    # Snapshot pages must contain at least one stable signal. An empty page is
    # a capture failure, not a website/function update.
    has_signal = bool(page.get('headings') or page.get('nav') or page.get('buttons') or page.get('links'))
    return not has_signal


def is_noise_item(page_name: str, key: str, item) -> bool:
    """Return True for dynamic content that should not trigger user alerts."""
    if page_name == 'market_tools':
        # Market Tools is mostly external/news/calendar content and has proven
        # noisy. Treat its content diffs as non-actionable; separate health
        # checks cover scraper/login failures.
        return True
    if page_name == 'market_tools' and key == 'links':
        text = href = ''
        if isinstance(item, tuple) and len(item) >= 2:
            text, href = str(item[0] or ''), str(item[1] or '')
        else:
            text = str(item or '')
        combined = f'{text} {href}'
        if 'cnbc.com/' in combined or re.search(r'\b\d+\s*(m|h|d)\s+ago', combined, re.I):
            return True
    return False


def filtered_set(page_name: str, key: str, values):
    return {x for x in values if not is_noise_item(page_name, key, x)}


def load(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def normalize(snapshot: dict):
    pages = {}
    for p in snapshot.get('pages', []):
        name = p.get('name')
        if is_capture_error_page(p):
            # Never compare a failed/empty capture as if the site removed UI.
            continue
        pages[name] = {
            'title': p.get('title'),
            'headings': sorted(set(p.get('headings') or [])),
            'nav': sorted(set(p.get('nav') or [])),
            'buttons': sorted(set(p.get('buttons') or [])),
            'links': sorted(set((x.get('text',''), x.get('href','')) for x in (p.get('links') or []))),
        }
    return pages


def failed_pages(snapshot: dict):
    return sorted(str(p.get('name')) for p in snapshot.get('pages', []) if is_capture_error_page(p))


def diff(old, new):
    # If latest snapshot had page capture failures, suppress site-change alerts.
    # A timeout means "unknown", not "page/nav removed".
    if failed_pages(new):
        return []
    oldn, newn = normalize(old), normalize(new)
    lines = []
    for name in sorted(set(oldn) | set(newn)):
        if name not in oldn:
            lines.append(f'New page captured: {name}')
            continue
        if name not in newn:
            # Missing in the old snapshot usually means the old capture failed;
            # do not alert that UI was "added" on recovery.
            continue
        for key in ['headings', 'nav', 'buttons', 'links']:
            oldset = filtered_set(name, key, set(map(str, oldn[name].get(key) or [])))
            newset = filtered_set(name, key, set(map(str, newn[name].get(key) or [])))
            added = sorted(newset - oldset)
            removed = sorted(oldset - newset)
            if added:
                lines.append(f'{name} {key} added: ' + '; '.join(added[:8]))
            if removed:
                lines.append(f'{name} {key} removed: ' + '; '.join(removed[:8]))
    return lines


def screenshot_attachments(snapshot: dict) -> list[Path]:
    screenshots = snapshot.get('screenshots') or {}
    out: list[Path] = []
    for key in ['dashboard', 'monthly', 'weekly']:
        value = screenshots.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists() and path.is_file():
            out.append(path)
    return out


def send_email(subject, body, attachments=None):
    env = load_env(ROOT)
    recipients = recipients_for_route(EmailRoute.ADMIN, env)
    if not recipients:
        return
    deliver_email(subject, body, to=recipients, attachments=attachments or [])


def main():
    old, new = load(PREVIOUS), load(LATEST)
    if not old or not new:
        return
    changes = diff(old, new)
    if not changes:
        return
    attachments = screenshot_attachments(new)
    body = '\n'.join([
        'Quant GT Website / Function Update',
        f'Detected: {datetime.now(timezone.utc).isoformat()}',
        '',
        'Changes:',
        *[f'- {c}' for c in changes[:30]],
        '',
        'Action: review whether selectors, navigation, or report fields need updating.',
    ])
    if attachments:
        body += '\n\nAttachments:\n' + '\n'.join(f'- {p.name}' for p in attachments)
    atomic_write_json(LAST_NOTE, {'subject':'Quant GT Website Update Detected','body':body,'at':datetime.now(timezone.utc).isoformat(),'changes':changes,'attachments':[str(p) for p in attachments]})
    send_email('Quant GT Website Update Detected', body, attachments=attachments)
    print('Quant GT Website Update Detected')
    print(body)


if __name__ == '__main__':
    main()
