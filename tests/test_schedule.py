import unittest

from quantcheck.schedule import DEFAULT_SCHEDULE, parse_schedule


class ScheduleTests(unittest.TestCase):
    def test_empty_schedule_uses_default(self):
        self.assertEqual(parse_schedule(""), DEFAULT_SCHEDULE)

    def test_custom_schedule_parses_kinds(self):
        self.assertEqual(
            parse_schedule("08:20:official_mail,08:30:picks,17:15:health_site"),
            [(8, 20, "official_mail"), (8, 30, "picks"), (17, 15, "health_site")],
        )

    def test_invalid_schedule_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_schedule("08:30:unknown")


if __name__ == "__main__":
    unittest.main()
