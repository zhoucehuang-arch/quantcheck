from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from quantcheck.state import atomic_write_json, load_json


def notification_fingerprint(diff: Dict[str, Any], data: Dict[str, Any]) -> str:
    payload = {
        "diff": diff,
        "monthly_symbols": [r.get("symbol") or r.get("company") for r in data.get("monthly", {}).get("rows", []) or []],
        "weekly_symbols": [r.get("symbol") or r.get("company") for r in data.get("weekly", {}).get("rows", []) or []],
        "monthly_date": data.get("monthly", {}).get("pick_date"),
        "weekly_date": data.get("weekly", {}).get("pick_date"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def should_send_notification(diff: Dict[str, Any], data: Dict[str, Any], dedupe_path: Path) -> bool:
    fingerprint = notification_fingerprint(diff, data)
    previous = load_json(dedupe_path, default={}) or {}
    if previous.get("fingerprint") == fingerprint:
        return False
    atomic_write_json(dedupe_path, {
        "fingerprint": fingerprint,
        "at": data.get("fetched_at"),
        "monthly_date": data.get("monthly", {}).get("pick_date"),
        "weekly_date": data.get("weekly", {}).get("pick_date"),
    })
    return True
