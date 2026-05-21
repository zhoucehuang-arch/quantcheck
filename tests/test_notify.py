import tempfile
import unittest
from pathlib import Path

from quantcheck.gmail_api_notify import parse_recipients


class NotifyTests(unittest.TestCase):
    def test_parse_recipients_splits_commas_and_semicolons(self):
        self.assertEqual(
            parse_recipients("a@example.com; b@example.com, a@example.com", file_path=""),
            ["a@example.com", "b@example.com"],
        )

    def test_parse_recipients_reads_file_and_merges_inline_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipient_file = Path(tmp) / "notify_recipients.txt"
            recipient_file.write_text(
                "# primary recipients\n"
                "a@example.com\n"
                "b@example.com, c@example.com\n"
                "a@example.com\n"
                "\n",
                encoding="utf-8",
            )

            self.assertEqual(
                parse_recipients("inline@example.com", file_path=recipient_file),
                ["inline@example.com", "a@example.com", "b@example.com", "c@example.com"],
            )


if __name__ == "__main__":
    unittest.main()
