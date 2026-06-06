import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path

from quantcheck.gmail_api_notify import parse_recipients, send_email, send_via_gmail_api
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

    def test_send_email_sends_one_private_message_per_recipient(self):
        calls = []

        def fake_gmail(subject, body, to=None, attachments=None, html=None):
            calls.append(list(to or []))
            return True

        with patch("quantcheck.gmail_api_notify.send_via_gmail_api", side_effect=fake_gmail), \
             patch("quantcheck.gmail_api_notify.send_via_smtp") as smtp:
            self.assertTrue(send_email("Subject", "Body", to=["a@example.com", "b@example.com"]))

        self.assertEqual(calls, [["a@example.com"], ["b@example.com"]])
        smtp.assert_not_called()
    def test_gmail_api_send_uses_full_scope_family(self):
        captured = {}

        class FakeCreds:
            expired = False
            refresh_token = None
            valid = True

            def to_json(self):
                return "{}"

        class FakeSend:
            def execute(self):
                return {"id": "msg-1"}

        class FakeMessages:
            def send(self, userId=None, body=None):
                captured["userId"] = userId
                captured["body"] = body
                return FakeSend()

        class FakeUsers:
            def messages(self):
                return FakeMessages()

        class FakeService:
            def users(self):
                return FakeUsers()

        def fake_from_token(path, scopes):
            captured["token_path"] = path
            captured["scopes"] = scopes
            return FakeCreds()

        fake_credentials_module = types.SimpleNamespace(
            Credentials=types.SimpleNamespace(from_authorized_user_file=fake_from_token)
        )
        fake_requests_module = types.SimpleNamespace(Request=lambda: object())
        fake_discovery_module = types.SimpleNamespace(build=lambda *args, **kwargs: FakeService())

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            sys.modules,
            {
                "google": types.ModuleType("google"),
                "google.oauth2": types.ModuleType("google.oauth2"),
                "google.oauth2.credentials": fake_credentials_module,
                "google.auth": types.ModuleType("google.auth"),
                "google.auth.transport": types.ModuleType("google.auth.transport"),
                "google.auth.transport.requests": fake_requests_module,
                "googleapiclient": types.ModuleType("googleapiclient"),
                "googleapiclient.discovery": fake_discovery_module,
            },
        ), patch.dict(
            "os.environ",
            {
                "GMAIL_API_ENABLED": "1",
                "GMAIL_API_TOKEN": str(Path(tmp) / "token.json"),
                "GMAIL_API_FROM": "sender@example.com",
            },
            clear=True,
        ):
            Path(tmp, "token.json").write_text("{}", encoding="utf-8")
            self.assertTrue(send_via_gmail_api("Subject", "Body", to=["admin@example.com"]))

        self.assertEqual(
            captured["scopes"],
            [
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.compose",
            ],
        )
        self.assertEqual(captured["userId"], "me")

    def test_gmail_api_send_appends_custom_scopes_without_duplicates(self):
        captured = {}

        class FakeCreds:
            expired = False
            refresh_token = None
            valid = True

        def fake_from_token(path, scopes):
            captured["scopes"] = scopes
            return FakeCreds()

        fake_credentials_module = types.SimpleNamespace(
            Credentials=types.SimpleNamespace(from_authorized_user_file=fake_from_token)
        )
        fake_requests_module = types.SimpleNamespace(Request=lambda: object())
        fake_discovery_module = types.SimpleNamespace(
            build=lambda *args, **kwargs: types.SimpleNamespace(
                users=lambda: types.SimpleNamespace(
                    messages=lambda: types.SimpleNamespace(
                        send=lambda **kwargs: types.SimpleNamespace(execute=lambda: {})
                    )
                )
            )
        )

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            sys.modules,
            {
                "google": types.ModuleType("google"),
                "google.oauth2": types.ModuleType("google.oauth2"),
                "google.oauth2.credentials": fake_credentials_module,
                "google.auth": types.ModuleType("google.auth"),
                "google.auth.transport": types.ModuleType("google.auth.transport"),
                "google.auth.transport.requests": fake_requests_module,
                "googleapiclient": types.ModuleType("googleapiclient"),
                "googleapiclient.discovery": fake_discovery_module,
            },
        ), patch.dict(
            "os.environ",
            {
                "GMAIL_API_ENABLED": "1",
                "GMAIL_API_TOKEN": str(Path(tmp) / "token.json"),
                "GMAIL_API_FROM": "sender@example.com",
                "GMAIL_API_SCOPES": "https://www.googleapis.com/auth/gmail.send, https://mail.google.com/",
            },
            clear=True,
        ):
            Path(tmp, "token.json").write_text("{}", encoding="utf-8")
            self.assertTrue(send_via_gmail_api("Subject", "Body", to=["admin@example.com"]))

        self.assertEqual(captured["scopes"].count("https://www.googleapis.com/auth/gmail.send"), 1)
        self.assertIn("https://mail.google.com/", captured["scopes"])


if __name__ == "__main__":
    unittest.main()
