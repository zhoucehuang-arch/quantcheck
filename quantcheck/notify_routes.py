from __future__ import annotations

import os
from enum import Enum
from typing import Iterable, List, Mapping

from quantcheck.gmail_api_notify import parse_recipients


class EmailRoute(str, Enum):
    PICKS_UPDATE = "picks_update"
    ADMIN = "admin"


def _unique(recipients: Iterable[str]) -> List[str]:
    out: list[str] = []
    seen: set[str] = set()
    for recipient in recipients:
        value = str(recipient or "").strip()
        key = value.lower()
        if not value or key in seen:
            continue
        out.append(value)
        seen.add(key)
    return out


def _setting(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key) or os.environ.get(key) or "")


def subscriber_recipients(env: Mapping[str, str]) -> List[str]:
    return parse_recipients(_setting(env, "NOTIFY_EMAIL_TO"), file_path=_setting(env, "NOTIFY_EMAIL_FILE"))


def admin_recipients(env: Mapping[str, str]) -> List[str]:
    return parse_recipients(_setting(env, "NOTIFY_ADMIN_EMAIL_TO"), file_path=_setting(env, "NOTIFY_ADMIN_EMAIL_FILE"))


def recipients_for_route(route: EmailRoute | str, env: Mapping[str, str]) -> List[str]:
    route = EmailRoute(route)
    subscribers = subscriber_recipients(env)
    admins = admin_recipients(env)
    if route == EmailRoute.PICKS_UPDATE:
        return _unique([*subscribers, *admins])
    return admins


def route_label(route: EmailRoute | str) -> str:
    route = EmailRoute(route)
    if route == EmailRoute.PICKS_UPDATE:
        return "picks update recipients"
    return "admin recipients"
