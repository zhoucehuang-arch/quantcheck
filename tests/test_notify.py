import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from quantcheck.gmail_api_notify import parse_recipients
from quantcheck.notify_routes import EmailRoute, admin_recipients, recipients_for_route, subscriber_recipients


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

    def test_picks_update_goes_to_subscribers_and_admins(self):
        env = {
            "NOTIFY_EMAIL_TO": "friend@example.com",
            "NOTIFY_EMAIL_FILE": "",
            "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com, friend@example.com",
            "NOTIFY_ADMIN_EMAIL_FILE": "",
        }

        self.assertEqual(
            recipients_for_route(EmailRoute.PICKS_UPDATE, env),
            ["friend@example.com", "admin@example.com"],
        )

    def test_admin_route_never_falls_back_to_subscribers(self):
        env = {
            "NOTIFY_EMAIL_TO": "friend@example.com",
            "NOTIFY_EMAIL_FILE": "",
            "NOTIFY_ADMIN_EMAIL_TO": "",
            "NOTIFY_ADMIN_EMAIL_FILE": "",
        }

        self.assertEqual(recipients_for_route(EmailRoute.ADMIN, env), [])

    def test_admin_route_never_falls_back_to_environment_subscribers(self):
        with patch.dict("os.environ", {"NOTIFY_EMAIL_TO": "friend@example.com", "NOTIFY_EMAIL_FILE": ""}, clear=True):
            self.assertEqual(recipients_for_route(EmailRoute.ADMIN, {}), [])

    def test_admin_and_subscriber_files_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            subscriber_file = Path(tmp) / "subscribers.txt"
            admin_file = Path(tmp) / "admins.txt"
            subscriber_file.write_text("friend@example.com\n", encoding="utf-8")
            admin_file.write_text("admin@example.com\n", encoding="utf-8")
            env = {
                "NOTIFY_EMAIL_TO": "",
                "NOTIFY_EMAIL_FILE": str(subscriber_file),
                "NOTIFY_ADMIN_EMAIL_TO": "",
                "NOTIFY_ADMIN_EMAIL_FILE": str(admin_file),
            }

            self.assertEqual(subscriber_recipients(env), ["friend@example.com"])
            self.assertEqual(admin_recipients(env), ["admin@example.com"])
            self.assertEqual(
                recipients_for_route(EmailRoute.PICKS_UPDATE, env),
                ["friend@example.com", "admin@example.com"],
            )


if __name__ == "__main__":
    unittest.main()
