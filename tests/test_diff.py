import unittest

from quantcheck.diff import compare, diff_rows, parse_analyst_signal


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


if __name__ == "__main__":
    unittest.main()
