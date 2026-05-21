import unittest

from quantcheck.validation import validate_member_picks_data


def valid_capture():
    return {
        "monthly": {"pick_date": "May 2026", "rows": [{"symbol": "M1"}]},
        "weekly": {
            "pick_date": "05/22/26",
            "rows": [
                {
                    "symbol": "W1",
                    "current_price": "$10.00",
                    "buy_or_entry_price": "$9.50",
                    "next_earnings": "2026-06-01",
                    "analyst_signal": "Buy +0.20",
                }
            ],
        },
    }


class ValidationTests(unittest.TestCase):
    def test_valid_member_capture_passes(self):
        validate_member_picks_data(valid_capture())

    def test_demo_weekly_signature_is_rejected(self):
        data = valid_capture()
        data["weekly"]["pick_date"] = "05/15/26"
        data["weekly"]["rows"] = [
            {"symbol": symbol, "current_price": "$1", "buy_or_entry_price": "$1", "next_earnings": "x", "analyst_signal": "x"}
            for symbol in ["SNDK", "LITE", "AAOI", "FORM", "VIAV", "ENPH"]
        ]

        with self.assertRaisesRegex(RuntimeError, "demo Weekly Picks"):
            validate_member_picks_data(data)

    def test_partial_weekly_details_are_rejected(self):
        data = valid_capture()
        data["weekly"]["rows"][0]["analyst_signal"] = ""

        with self.assertRaisesRegex(RuntimeError, "incomplete detail rows"):
            validate_member_picks_data(data)


if __name__ == "__main__":
    unittest.main()
