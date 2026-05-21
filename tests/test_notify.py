import unittest

from quantcheck.gmail_api_notify import parse_recipients


class NotifyTests(unittest.TestCase):
    def test_parse_recipients_splits_commas_and_semicolons(self):
        self.assertEqual(
            parse_recipients("a@example.com; b@example.com, a@example.com"),
            ["a@example.com", "b@example.com"],
        )


if __name__ == "__main__":
    unittest.main()
