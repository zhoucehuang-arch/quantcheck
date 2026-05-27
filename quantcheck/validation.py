from __future__ import annotations

from typing import Any, Dict


def validate_member_picks_data(data: Dict[str, Any]) -> None:
    """Reject unauthenticated/demo or partial Quant GT captures before state writes."""
    monthly = data.get("monthly") or {}
    weekly = data.get("weekly") or {}
    weekly_rows = weekly.get("rows") or []
    if not weekly_rows:
        raise RuntimeError("logged-in weekly picks validation failed: no weekly rows captured")
    weekly_date = str(weekly.get("pick_date") or "")
    weekly_symbols = [str(row.get("symbol") or "") for row in weekly_rows]
    generic_detail_rows = [
        row for row in weekly_rows
        if "This company designs, develops, and markets a range of consumer and enterprise technology products and services worldwide" in str(row.get("relative_strength") or "")
    ]
    current_prices = {str(row.get("current_price") or "") for row in weekly_rows if row.get("current_price")}
    demo_symbol_set = {"SNDK", "LITE", "AAOI", "FORM", "VIAV", "ENPH"}
    if weekly_date == "05/15/26" and demo_symbol_set.issubset(set(weekly_symbols)):
        raise RuntimeError("rejected unauthenticated/demo Weekly Picks signature: 05/15/26")
    if len(generic_detail_rows) >= max(3, len(weekly_rows) // 2):
        raise RuntimeError("rejected unauthenticated/demo Weekly Picks signature: generic placeholder details")
    if len(weekly_rows) >= 5 and len(current_prices) == 1 and "$184.62" in current_prices:
        raise RuntimeError("rejected unauthenticated/demo Weekly Picks signature: repeated fake current price")
    if not (monthly.get("rows") or []):
        raise RuntimeError("logged-in monthly picks validation failed: no monthly rows captured")

    monthly_rows = monthly.get("rows") or []
    required_monthly_fields = ["symbol", "company", "current_price", "return", "sector", "gt_score", "buy_or_entry_price", "next_earnings", "analyst_signal"]
    bad_monthly = []
    for row in monthly_rows:
        missing = [field for field in required_monthly_fields if row.get(field) in (None, "")]
        if missing:
            bad_monthly.append(f"{row.get('symbol') or row.get('company') or '?'} missing {','.join(missing)}")
    if bad_monthly:
        raise RuntimeError("logged-in monthly picks validation failed: incomplete loaded rows: " + "; ".join(bad_monthly[:5]))

    required_weekly_detail_fields = ["symbol", "company", "current_price", "buy_or_entry_price", "sector", "gt_score", "next_earnings", "analyst_signal"]
    complete_detail_rows = [
        row for row in weekly_rows
        if all(row.get(field) not in (None, "") for field in required_weekly_detail_fields)
    ]
    detailish_rows = [
        row for row in weekly_rows
        if any(row.get(field) not in (None, "") for field in required_weekly_detail_fields)
    ]
    if detailish_rows and len(complete_detail_rows) != len(weekly_rows):
        bad_weekly = []
        for row in weekly_rows:
            missing = [field for field in required_weekly_detail_fields if row.get(field) in (None, "")]
            if missing:
                bad_weekly.append(f"{row.get('symbol') or row.get('company') or '?'} missing {','.join(missing)}")
        raise RuntimeError("logged-in weekly picks validation failed: incomplete detail rows: " + "; ".join(bad_weekly[:5]))
