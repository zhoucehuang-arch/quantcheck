import os
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from quantcheck.schedule import (
    NON_TRADING_DAY_SCHEDULE,
    TRADING_DAY_SCHEDULE,
    parse_schedule,
    schedule_for_date,
)
from quantcheck.picks_check import current_window


class ScheduleTests(unittest.TestCase):
    def test_empty_schedule_uses_dynamic_trading_day_default(self):
        self.assertEqual(parse_schedule("", current_date=date(2026, 5, 26)), TRADING_DAY_SCHEDULE)

    def test_empty_schedule_uses_non_trading_day_default(self):
        self.assertEqual(parse_schedule("", current_date=date(2026, 5, 30)), NON_TRADING_DAY_SCHEDULE)

    def test_trading_day_schedule_matches_operational_scan_plan(self):
        self.assertEqual(
            TRADING_DAY_SCHEDULE,
            [
                (8, 20, "official_mail"),
                (8, 30, "picks"),
                (8, 45, "health_site"),
                (9, 0, "picks"),
                (9, 20, "official_mail"),
                (9, 40, "picks"),
                (12, 0, "official_mail"),
                (12, 40, "daily_admin_status"),
                (17, 0, "picks"),
                (17, 15, "health_site"),
                (17, 30, "official_mail"),
            ],
        )

    def test_non_trading_day_schedule_runs_daily_picks_mail_and_admin_status(self):
        self.assertEqual(
            NON_TRADING_DAY_SCHEDULE,
            [(12, 0, "picks"), (12, 20, "official_mail"), (12, 40, "daily_admin_status")],
        )

    def test_custom_schedule_parses_kinds(self):
        self.assertEqual(
            parse_schedule("08:20:official_mail,08:30:picks,12:40:daily_admin_status,17:15:health_site"),
            [(8, 20, "official_mail"), (8, 30, "picks"), (12, 40, "daily_admin_status"), (17, 15, "health_site")],
        )

    def test_invalid_schedule_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_schedule("08:30:unknown")

    def test_schedule_for_date_treats_market_holiday_as_non_trading_day(self):
        # Memorial Day 2026: NYSE closed.
        self.assertEqual(schedule_for_date(date(2026, 5, 25)), NON_TRADING_DAY_SCHEDULE)

    def test_current_window_has_no_open_0940_window_and_has_daily_non_trading(self):
        ny = ZoneInfo("America/New_York")
        self.assertEqual(current_window(datetime(2026, 5, 26, 8, 30, tzinfo=ny)), "premarket_0830")
        self.assertEqual(current_window(datetime(2026, 5, 26, 9, 0, tzinfo=ny)), "premarket_0900")
        self.assertIsNone(current_window(datetime(2026, 5, 26, 9, 40, tzinfo=ny)))
        self.assertEqual(current_window(datetime(2026, 5, 30, 12, 0, tzinfo=ny)), "daily_non_trading_1200")

    def test_default_picks_run_has_no_global_timeout(self):
        import quantcheck.scheduler as scheduler

        captured = {}

        def fake_run_cmd(args, timeout):
            captured["timeout"] = timeout
            return 0

        with patch.dict(os.environ, {}, clear=True), patch.object(scheduler, "run_cmd", side_effect=fake_run_cmd):
            self.assertEqual(scheduler.run_picks(), 0)

        self.assertIsNone(captured["timeout"])


if __name__ == "__main__":
    unittest.main()
