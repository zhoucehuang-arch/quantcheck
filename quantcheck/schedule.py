from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas_market_calendars as mcal

TRADING_DAY_SCHEDULE = [
    # US regular open is 09:30 America/New_York.
    # Run two premarket scans: 1 hour and 30 minutes before open.
    (8, 30, "picks"),
    (9, 0, "picks"),
    # One postmarket scan after the regular close.
    (17, 0, "picks"),
]

NON_TRADING_DAY_SCHEDULE = [
    # Weekends and market holidays: one midday sweep is enough.
    (12, 0, "picks"),
]

VALID_KINDS = {"picks", "health_site", "health", "official_mail"}


@lru_cache(maxsize=8)
def _nyse_calendar():
    return mcal.get_calendar("NYSE")


def is_trading_day(day: date) -> bool:
    cal = _nyse_calendar()
    schedule = cal.schedule(start_date=day.isoformat(), end_date=day.isoformat())
    return not schedule.empty


def schedule_for_date(day: date):
    return TRADING_DAY_SCHEDULE if is_trading_day(day) else NON_TRADING_DAY_SCHEDULE


def parse_schedule(raw: str | None, current_date: date | None = None):
    if not raw:
        return schedule_for_date(current_date or date.today())
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        time_part, kind = item.rsplit(":", 1)
        hour, minute = [int(x) for x in time_part.split(":")]
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"invalid schedule time: {time_part}")
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid schedule kind: {kind}")
        out.append((hour, minute, kind))
    return out or schedule_for_date(current_date or date.today())
