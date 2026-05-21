from __future__ import annotations

import json
import re
from typing import Any, Dict, List


DYNAMIC_NOISE_FIELDS = {
    "return",
    "current_price",
    "chart_return",
    "market_cap",
    "pe_ttm",
    "buy_or_entry_price",
    "revenue_ttm",
    "revenue_growth_yoy",
    "next_earnings",
    "momentum",
    "relative_strength",
}

ANALYST_SIGNAL_MAJOR_DELTA = 0.30
ANALYST_SIGNAL_CATEGORY_DELTA = 0.25
ANALYST_SIGNAL_STRONG_DELTA = 0.15


def row_key(row: Dict[str, Any]) -> str:
    return row.get("symbol") or row.get("company") or json.dumps(row, sort_keys=True)


def parse_analyst_signal(value: Any) -> tuple[str, float | None]:
    """Parse strings like "Buy +0.27" into (label, score)."""
    text = str(value or "").strip()
    if not text:
        return "", None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", text)
    score = float(match.group(1)) if match else None
    label = text[: match.start()].strip() if match else text
    return re.sub(r"\s+", " ", label), score


def is_major_analyst_signal_change(old_value: Any, new_value: Any) -> bool:
    old_label, old_score = parse_analyst_signal(old_value)
    new_label, new_score = parse_analyst_signal(new_value)
    if str(old_value or "") == str(new_value or ""):
        return False
    if old_score is None or new_score is None:
        return old_label != new_label and {"Strong Buy", "Strong Sell"} & {old_label, new_label}
    delta = abs(new_score - old_score)
    if delta >= ANALYST_SIGNAL_MAJOR_DELTA:
        return True
    label_changed = old_label != new_label
    if label_changed and delta >= ANALYST_SIGNAL_CATEGORY_DELTA:
        return True
    if label_changed and ({old_label, new_label} & {"Strong Buy", "Strong Sell"}) and delta >= ANALYST_SIGNAL_STRONG_DELTA:
        return True
    return False


def diff_rows(old_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    old_map = {row_key(row): row for row in old_rows}
    new_map = {row_key(row): row for row in new_rows}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    changed = []
    for key in sorted(set(old_map) & set(new_map)):
        fields = {}
        keys = sorted(set(old_map[key]) | set(new_map[key]))
        for field in keys:
            if field in {"detail_error"} or field in DYNAMIC_NOISE_FIELDS:
                continue
            old_value = old_map[key].get(field, "")
            new_value = new_map[key].get(field, "")
            if field == "analyst_signal":
                if is_major_analyst_signal_change(old_value, new_value):
                    fields[field] = {"old": old_value, "new": new_value}
                continue
            if str(old_value) != str(new_value):
                fields[field] = {"old": old_value, "new": new_value}
        if fields:
            changed.append({"symbol": key, "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def compare(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    result = {"changed": False, "monthly": {}, "weekly": {}}
    for section in ["monthly", "weekly"]:
        sec = {}
        old_date = old.get(section, {}).get("pick_date")
        new_date = new.get(section, {}).get("pick_date")
        if old_date != new_date and old_date not in (None, "", "Unknown") and new_date not in (None, "", "Unknown"):
            sec["date"] = {"old": old_date, "new": new_date}
        row_diff = diff_rows(old.get(section, {}).get("rows", []), new.get(section, {}).get("rows", []))
        sec.update(row_diff)
        sec_changed = bool(sec.get("date") or sec.get("added") or sec.get("removed") or sec.get("changed"))
        sec["changed_flag"] = sec_changed
        result[section] = sec
        result["changed"] = result["changed"] or sec_changed
    return result
