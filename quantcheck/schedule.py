from __future__ import annotations


DEFAULT_SCHEDULE = [
    (8, 20, "official_mail"),
    (8, 30, "picks"),
    (8, 45, "health_site"),
    (9, 0, "picks"),
    (9, 20, "official_mail"),
    (9, 40, "picks"),
    (12, 0, "official_mail"),
    (17, 0, "picks"),
    (17, 15, "health_site"),
    (17, 30, "official_mail"),
]


def parse_schedule(raw: str | None):
    if not raw:
        return DEFAULT_SCHEDULE
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        time_part, kind = item.rsplit(":", 1)
        hour, minute = [int(x) for x in time_part.split(":")]
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"invalid schedule time: {time_part}")
        if kind not in {"picks", "health_site", "health", "official_mail"}:
            raise ValueError(f"invalid schedule kind: {kind}")
        out.append((hour, minute, kind))
    return out or DEFAULT_SCHEDULE
