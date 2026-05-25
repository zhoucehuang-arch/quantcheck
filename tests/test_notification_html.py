import unittest
import sys
import types

sys.modules.setdefault("pandas_market_calendars", types.SimpleNamespace())
sys.modules.setdefault("playwright", types.ModuleType("playwright"))
sys.modules.setdefault(
    "playwright.sync_api",
    types.SimpleNamespace(sync_playwright=lambda: None, TimeoutError=TimeoutError),
)
from quantcheck.picks_check import build_notification_html


class NotificationHtmlTests(unittest.TestCase):
    def test_changes_are_rendered_as_grouped_cards_not_single_long_list(self):
        data = {
            "fetched_at": "2026-05-24T16:10:09",
            "source": "https://quantgt.io",
            "monthly": {"pick_date": "Unknown", "rows": []},
            "weekly": {"pick_date": "Week of May 25, 2026", "rows": []},
        }
        diff = {
            "changed": True,
            "monthly": {
                "changed_flag": True,
                "date": None,
                "added": [],
                "removed": [],
                "changed": [
                    {"symbol": "AAOI", "fields": {"analyst_signal": {"old": "Neutral +0.02", "new": "Buy +0.45"}, "held_since": {"old": "04/2026", "new": "2026-04-01"}}},
                ],
            },
            "weekly": {
                "changed_flag": True,
                "date": {"old": "05/11/26", "new": "Week of May 25, 2026"},
                "added": ["INTC", "STX"],
                "removed": ["GLW", "PL"],
                "changed": [
                    {"symbol": "DOCN", "fields": {"analyst_signal": {"old": "Strong Buy +0.60", "new": "Buy +0.38"}, "gt_score": {"old": "4.41/5", "new": "4.53/5"}}},
                ],
            },
        }

        html = build_notification_html(data, diff, context="picks changed · window=forced")

        self.assertIn("Changes Summary", html)
        self.assertIn("Monthly Picks", html)
        self.assertIn("Weekly Picks", html)
        self.assertIn("Added", html)
        self.assertIn("Removed", html)
        self.assertIn("INTC", html)
        self.assertIn("GLW", html)
        self.assertIn("AAOI", html)
        self.assertIn("DOCN", html)
        self.assertIn("Neutral +0.02", html)
        self.assertIn("Buy +0.45", html)
        self.assertIn("Strong Buy +0.60", html)
        self.assertIn("Buy +0.38", html)
        self.assertIn("→", html)
        self.assertNotIn("<ul", html)

    def test_changes_use_email_safe_tables_aligned_with_picks_tables(self):
        data = {
            "fetched_at": "2026-05-24T16:10:09",
            "source": "https://quantgt.io",
            "monthly": {"pick_date": "Unknown", "rows": []},
            "weekly": {"pick_date": "Week of May 25, 2026", "rows": []},
        }
        diff = {
            "changed": True,
            "monthly": {
                "changed_flag": True,
                "date": None,
                "added": [],
                "removed": [],
                "changed": [
                    {"symbol": "AAOI", "fields": {"analyst_signal": {"old": "Neutral +0.02", "new": "Buy +0.45"}}},
                ],
            },
            "weekly": {"changed_flag": False, "date": None, "added": [], "removed": [], "changed": []},
        }

        html = build_notification_html(data, diff, context="layout test")

        self.assertIn('min-width:980px', html)
        self.assertIn('min-width:760px', html)
        self.assertIn('Field', html)
        self.assertIn('Previous', html)
        self.assertIn('New', html)
        self.assertIn('<td style=', html)
        self.assertIn('font-size:14px', html)
        self.assertNotIn('display:inline-block;color:#64748b', html)
        self.assertNotIn('min-width:98px', html)


if __name__ == "__main__":
    unittest.main()
