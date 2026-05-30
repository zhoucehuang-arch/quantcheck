import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("playwright", types.ModuleType("playwright"))
sys.modules.setdefault(
    "playwright.sync_api",
    types.SimpleNamespace(sync_playwright=lambda: None, TimeoutError=TimeoutError),
)

from quantcheck import picks_check
from quantcheck.notify_routes import EmailRoute


def weekly_row(symbol="W1"):
    return {
        "symbol": symbol,
        "company": "Weekly One Inc.",
        "current_price": "$10.00",
        "buy_or_entry_price": "$9.50",
        "sector": "Technology",
        "gt_score": "4.20/5",
        "next_earnings": "2026-06-01",
        "analyst_signal": "Buy +0.20",
    }


VALID_DATA = {
    "fetched_at": "2026-05-27T14:30:00",
    "source": "https://quantgt.io",
    "monthly": {
        "pick_date": "May Holdings 05/01/26 - now",
        "rows": [
            {
                "symbol": "M1",
                "company": "Monthly One Inc.",
                "current_price": "$20.00",
                "return": "+12.30%",
                "sector": "Technology",
                "gt_score": "4.50/5",
                "buy_or_entry_price": "$18.00",
                "next_earnings": "2026-06-15",
                "analyst_signal": "Buy +0.25",
            }
        ],
    },
    "weekly": {
        "pick_date": "Week of May 25, 2026",
        "rows": [weekly_row(f"W{i}") for i in range(1, 11)],
    },
}


class FetchResilienceTests(unittest.TestCase):
    def test_fetch_current_retries_transient_failed_capture_before_returning_data(self):
        attempts = []

        def flaky_fetch():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("logged-in monthly picks validation failed: no monthly rows captured")
            return VALID_DATA

        with patch.object(picks_check.report, "fetch", side_effect=flaky_fetch), \
             patch.object(picks_check, "log"), \
             patch.object(picks_check, "json_dump"), \
             patch.object(picks_check, "prune_old_files"):
            data = picks_check.fetch_current(max_attempts=2, retry_delay_seconds=0)

        self.assertEqual(data["monthly"]["rows"][0]["symbol"], "M1")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(data["auth_verified"])

    def test_manual_test_email_failure_notifies_admin_route(self):
        sent = []

        def fake_notify(subject, body, media=None, html_body=None, telegram_body=None, route=EmailRoute.PICKS_UPDATE):
            sent.append({"subject": subject, "body": body, "html_body": html_body, "route": route, "media": media or []})

        with patch.object(picks_check, "fetch_current", side_effect=RuntimeError("monthly rows stayed empty after retries")), \
             patch.object(picks_check, "notify", side_effect=fake_notify), \
             patch.object(picks_check, "log"), \
             patch.object(picks_check, "write_health"), \
             patch.object(picks_check, "json_load", return_value={}):
            with self.assertRaises(RuntimeError):
                picks_check.run_test_email()

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["route"], EmailRoute.ADMIN)
        self.assertIn("Quant GT Monitor Test Failed", sent[0]["subject"])
        self.assertIn("monthly rows stayed empty", sent[0]["body"])
        self.assertIsNotNone(sent[0]["html_body"])
        self.assertIn("Quant GT Monitor", sent[0]["html_body"])
        self.assertIn("Error", sent[0]["html_body"])
        self.assertIn("monthly rows stayed empty", sent[0]["html_body"])

    def test_run_check_failure_notifies_admin_with_card_html(self):
        sent = []

        def fake_notify(subject, body, media=None, html_body=None, telegram_body=None, route=EmailRoute.PICKS_UPDATE):
            sent.append({"subject": subject, "body": body, "html_body": html_body, "route": route, "media": media or []})

        with patch.object(picks_check, "trading_day", return_value=True), \
             patch.object(picks_check, "current_window", return_value="premarket_0830"), \
             patch.object(picks_check, "fetch_current", side_effect=RuntimeError("monthly rows stayed empty after retries")), \
             patch.object(picks_check, "capture_logged_in_screenshots", return_value={}), \
             patch.object(picks_check, "notify", side_effect=fake_notify), \
             patch.object(picks_check, "log"), \
             patch.object(picks_check, "write_health"), \
             patch.object(picks_check, "json_load", return_value={}):
            with self.assertRaises(RuntimeError):
                picks_check.run_check(force=False, no_random=True)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["route"], EmailRoute.ADMIN)
        self.assertIn("Quant GT Monitor Failed", sent[0]["subject"])
        self.assertIsNotNone(sent[0]["html_body"])
        self.assertIn("Quant GT Monitor", sent[0]["html_body"])
        self.assertIn("monthly rows stayed empty", sent[0]["html_body"])


if __name__ == "__main__":
    unittest.main()
