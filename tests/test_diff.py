import copy
import tempfile
import unittest
from pathlib import Path

from quantcheck.diff import compare, diff_rows, parse_analyst_signal
from quantcheck.picks_check import should_send_notification


def sample_picks():
    return {
        "monthly": {
            "pick_date": "Unknown",
            "rows": [
                {
                    "symbol": "ABC",
                    "company": "Alpha Corp",
                    "return": "+1.1%",
                    "rating": "Buy",
                    "gt_score": "91",
                    "current_price": "$10.00",
                    "buy_or_entry_price": "$9.50",
                }
            ],
        },
        "weekly": {
            "pick_date": "05/11/26",
            "rows": [
                {
                    "symbol": "XYZ",
                    "company": "Xylon Inc",
                    "sector": "Tech",
                    "rating": "Strong Buy",
                    "gt_score": "88",
                    "current_price": "$20.00",
                    "buy_or_entry_price": "$18.00",
                    "analyst_signal": "Buy +0.26",
                }
            ],
        },
    }


class DiffTests(unittest.TestCase):
    def test_dynamic_price_fields_do_not_trigger_pick_change(self):
        old = [{"symbol": "ABC", "company": "Alpha", "current_price": "$10.00", "rating": "Buy"}]
        new = [{"symbol": "ABC", "company": "Alpha", "current_price": "$11.00", "rating": "Buy"}]

        self.assertEqual(diff_rows(old, new), {"added": [], "removed": [], "changed": []})

    def test_static_field_change_is_reported(self):
        old = [{"symbol": "ABC", "company": "Alpha", "rating": "Buy"}]
        new = [{"symbol": "ABC", "company": "Alpha", "rating": "Hold"}]

        self.assertEqual(
            diff_rows(old, new)["changed"],
            [{"symbol": "ABC", "fields": {"rating": {"old": "Buy", "new": "Hold"}}}],
        )

    def test_unknown_dates_are_not_reported_as_source_changes(self):
        old = {"monthly": {"pick_date": "May 2026", "rows": []}, "weekly": {"pick_date": "Unknown", "rows": []}}
        new = {"monthly": {"pick_date": "Unknown", "rows": []}, "weekly": {"pick_date": "05/22/26", "rows": []}}

        self.assertFalse(compare(old, new)["changed"])

    def test_analyst_signal_score_is_parsed_from_suffix(self):
        self.assertEqual(parse_analyst_signal("Strong Buy +0.27"), ("Strong Buy", 0.27))

    def test_identical_picks_with_dynamic_fetch_metadata_do_not_trigger_duplicate_notification(self):
        old = sample_picks()
        new = copy.deepcopy(old)
        old["fetched_at"] = "2026-05-21T08:30:00-04:00"
        new["fetched_at"] = "2026-05-21T17:00:00-04:00"
        old["monthly"]["rows"][0]["current_price"] = "$10.00"
        new["monthly"]["rows"][0]["current_price"] = "$10.42"
        old["weekly"]["rows"][0]["current_price"] = "$20.00"
        new["weekly"]["rows"][0]["current_price"] = "$20.55"

        self.assertFalse(compare(old, new)["changed"])

    def test_small_analyst_signal_score_noise_does_not_trigger_duplicate_notification(self):
        old = sample_picks()
        new = copy.deepcopy(old)
        old["weekly"]["rows"][0]["analyst_signal"] = "Buy +0.26"
        new["weekly"]["rows"][0]["analyst_signal"] = "Buy +0.29"

        self.assertFalse(compare(old, new)["changed"])
    def test_same_changed_payload_is_not_notified_twice(self):
        old = sample_picks()
        new = copy.deepcopy(old)
        new["weekly"]["rows"].append({"symbol": "NEW", "company": "New Co", "rating": "Buy"})
        diff = compare(old, new)
        self.assertTrue(diff["changed"])

        with tempfile.TemporaryDirectory() as tmp:
            dedupe_path = Path(tmp) / "last_picks_change_notification.json"
            self.assertTrue(should_send_notification(diff, new, dedupe_path=dedupe_path))
            self.assertFalse(should_send_notification(diff, new, dedupe_path=dedupe_path))


if __name__ == "__main__":
    unittest.main()
