import unittest
import tempfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from quantcheck.official_mail_forwarder import (
    OfficialMail,
    build_forward_body,
    forward_official_mail,
    gmail_messages_to_official_mails,
    main,
    matches_official_mail,
    official_mail_from_message,
    split_patterns,
)


class OfficialMailForwarderTests(unittest.TestCase):
    def test_split_patterns_uses_defaults_and_separators(self):
        self.assertEqual(split_patterns("", ["quantgt"]), [])
        self.assertEqual(split_patterns(None, ["quantgt"]), ["quantgt"])
        self.assertEqual(split_patterns("QuantGT; Picks\nHoldings", []), ["quantgt", "picks", "holdings"])

    def test_message_body_and_headers_are_decoded(self):
        msg = EmailMessage()
        msg["From"] = "Quant GT <support@quantgt.io>"
        msg["Subject"] = "Monthly Picks Updated"
        msg["Date"] = "Mon, 25 May 2026 08:00:00 +0000"
        msg.set_content("New monthly picks are available.")

        mail = official_mail_from_message("1", msg.as_bytes())

        self.assertEqual(mail.uid, "1")
        self.assertEqual(mail.subject, "Monthly Picks Updated")
        self.assertIn("support@quantgt.io", mail.from_header)
        self.assertEqual(mail.text.strip(), "New monthly picks are available.")

    def test_official_mail_matching_requires_sender_and_subject(self):
        sender_patterns = ["@quantgt.io"]
        subject_patterns = ["picks", "holdings"]

        self.assertTrue(matches_official_mail(
            OfficialMail("1", "Monthly Picks Updated", "Quant GT <support@quantgt.io>", "", "", ""),
            sender_patterns,
            subject_patterns,
        ))
        self.assertFalse(matches_official_mail(
            OfficialMail("1", "Monthly Picks Updated", "Other <sender@example.com>", "", "", ""),
            sender_patterns,
            subject_patterns,
        ))
        self.assertFalse(matches_official_mail(
            OfficialMail("1", "Welcome", "Quant GT <support@quantgt.io>", "", "", ""),
            sender_patterns,
            subject_patterns,
        ))

    def test_forwarded_mail_matching_can_use_body_context(self):
        mail = OfficialMail(
            "1",
            "Fwd: Monthly Picks",
            "Me <owner@example.com>",
            "",
            "From: Quant GT <support@quantgt.io>\nSubject: Monthly Picks Updated",
            "",
        )

        self.assertTrue(matches_official_mail(mail, ["@quantgt.io"], ["picks"]))

    def test_matching_does_not_treat_plain_quantgt_mentions_as_official_sender(self):
        mail = OfficialMail(
            "1",
            "Quant GT Picks Updated",
            "Me <owner@example.com>",
            "",
            "Source: https://quantgt.io\nWeekly picks changed",
            "<p>Source: https://quantgt.io</p><p>Weekly picks changed</p>",
        )

        self.assertFalse(matches_official_mail(mail, ["@quantgt.io"], ["picks", "updated"]))

    def test_forward_body_preserves_official_message_context(self):
        mail = OfficialMail(
            "1",
            "Monthly Picks Updated",
            "Quant GT <support@quantgt.io>",
            "Mon, 25 May 2026 08:00:00 +0000",
            "The picks changed.",
            "<p>The picks changed.</p>",
        )

        subject, body, html = build_forward_body(mail)

        self.assertEqual(subject, "Quant GT Official Email: Monthly Picks Updated")
        self.assertIn("support@quantgt.io", body)
        self.assertIn("Monthly Picks Updated", body)
        self.assertIn("Forwarded official Quant GT email.", html)
        self.assertIn("Quant GT Monitor", html)
        self.assertIn("Official Email", html)
        self.assertIn("<p>The picks changed.</p>", html)

    def test_forwarder_is_disabled_by_default(self):
        with patch("quantcheck.official_mail_forwarder.connect_imap") as connect_imap:
            result = forward_official_mail({
                "NOTIFY_EMAIL_TO": "friend@example.com",
                "NOTIFY_EMAIL_FILE": "",
                "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
                "NOTIFY_ADMIN_EMAIL_FILE": "",
            })

        self.assertEqual(result["skipped"], "disabled")
        connect_imap.assert_not_called()

    def test_gmail_messages_are_converted_to_official_mails(self):
        messages = [{
            "id": "abc123",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Quant GT <support@quantgt.io>"},
                    {"name": "Subject", "value": "Monthly Picks Updated"},
                    {"name": "Date", "value": "Mon, 25 May 2026 08:00:00 +0000"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": "TmV3IHBpY2tzIGFyZSBhdmFpbGFibGUu"}},
                    {"mimeType": "text/html", "body": {"data": "PHA-TmV3IHBpY2tzIGFyZSBhdmFpbGFibGUuPC9wPg"}},
                ],
            },
        }]

        mails = gmail_messages_to_official_mails(messages)

        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0].uid, "abc123")
        self.assertEqual(mails[0].subject, "Monthly Picks Updated")
        self.assertIn("support@quantgt.io", mails[0].from_header)
        self.assertIn("New picks are available.", mails[0].text)
        self.assertIn("<p>New picks are available.</p>", mails[0].html)

    def test_forwarder_uses_gmail_and_marks_message_read(self):
        messages = [{
            "id": "abc123",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Quant GT <support@quantgt.io>"},
                    {"name": "Subject", "value": "Monthly Picks Updated"},
                    {"name": "Date", "value": "Mon, 25 May 2026 08:00:00 +0000"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": "TmV3IHBpY2tzIGFyZSBhdmFpbGFibGUu"}},
                ],
            },
        }]

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "official_mail_forwarder_state.json"
            env = {
                "OFFICIAL_MAIL_ENABLED": "1",
                "OFFICIAL_MAIL_PROVIDER": "gmail",
                "OFFICIAL_MAIL_GMAIL_QUERY": "is:unread",
                "NOTIFY_EMAIL_TO": "friend@example.com",
                "NOTIFY_EMAIL_FILE": "",
                "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
                "NOTIFY_ADMIN_EMAIL_FILE": "",
            }
            with (
                patch("quantcheck.official_mail_forwarder.STATE_FILE", state_file),
                patch("quantcheck.official_mail_forwarder.list_gmail_messages", return_value=messages),
                patch("quantcheck.official_mail_forwarder.mark_gmail_message_read") as mark_read,
                patch("quantcheck.official_mail_forwarder.deliver_email", return_value=(["ok@example.com"], [])) as deliver,
            ):
                first = forward_official_mail(env)
                second = forward_official_mail(env)

        self.assertEqual(first["provider"], "gmail")
        self.assertEqual(first["forwarded"], 1)
        self.assertEqual(second["forwarded"], 0)
        deliver.assert_called_once()
        mark_read.assert_called_once_with(env, "abc123")

    def test_forwarder_uses_imap_and_records_state(self):
        msg = EmailMessage()
        msg["From"] = "Quant GT <support@quantgt.io>"
        msg["Subject"] = "Monthly Picks Updated"
        msg["Date"] = "Mon, 25 May 2026 08:00:00 +0000"
        msg.set_content("New monthly picks are available.")

        class FakeImap:
            def select(self, mailbox, readonly=True):
                return "OK", []

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"1"]
                if command == "fetch":
                    return "OK", [(b"1 (RFC822 {1}", msg.as_bytes())]
                raise AssertionError(command)

            def logout(self):
                return "OK", []

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "official_mail_forwarder_state.json"
            env = {
                "OFFICIAL_MAIL_ENABLED": "1",
                "OFFICIAL_MAIL_PROVIDER": "imap",
                "NOTIFY_EMAIL_TO": "friend@example.com",
                "NOTIFY_EMAIL_FILE": "",
                "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
                "NOTIFY_ADMIN_EMAIL_FILE": "",
                "OFFICIAL_MAIL_IMAP_HOST": "imap.example.com",
                "OFFICIAL_MAIL_IMAP_USERNAME": "receiver@example.com",
                "OFFICIAL_MAIL_IMAP_PASSWORD": "secret",
                "OFFICIAL_MAIL_IMAP_SECURITY": "starttls",
            }
            with (
                patch("quantcheck.official_mail_forwarder.STATE_FILE", state_file),
                patch("quantcheck.official_mail_forwarder.connect_imap", return_value=FakeImap()),
                patch("quantcheck.official_mail_forwarder.deliver_email", return_value=(["ok@example.com"], [])) as deliver,
            ):
                first = forward_official_mail(env)
                second = forward_official_mail(env)

        self.assertEqual(first["forwarded"], 1)
        self.assertEqual(second["forwarded"], 0)
        deliver.assert_called_once()
        self.assertEqual(deliver.call_args.kwargs["to"], ["friend@example.com", "admin@example.com"])

    def test_forwarder_sends_once_and_records_state(self):
        msg = EmailMessage()
        msg["From"] = "Quant GT <support@quantgt.io>"
        msg["Subject"] = "Monthly Picks Updated"
        msg["Date"] = "Mon, 25 May 2026 08:00:00 +0000"
        msg.set_content("New monthly picks are available.")

        class FakeImap:
            def select(self, mailbox, readonly=True):
                return "OK", []

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"1"]
                if command == "fetch":
                    return "OK", [(b"1 (RFC822 {1}", msg.as_bytes())]
                raise AssertionError(command)

            def logout(self):
                return "OK", []

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "official_mail_forwarder_state.json"
            env = {
                "OFFICIAL_MAIL_ENABLED": "1",
                "OFFICIAL_MAIL_PROVIDER": "imap",
                "NOTIFY_EMAIL_TO": "friend@example.com",
                "NOTIFY_EMAIL_FILE": "",
                "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
                "NOTIFY_ADMIN_EMAIL_FILE": "",
                "OFFICIAL_MAIL_IMAP_HOST": "imap.example.com",
                "OFFICIAL_MAIL_IMAP_USERNAME": "receiver@example.com",
                "OFFICIAL_MAIL_IMAP_PASSWORD": "secret",
            }
            with (
                patch("quantcheck.official_mail_forwarder.STATE_FILE", state_file),
                patch("quantcheck.official_mail_forwarder.connect_imap", return_value=FakeImap()),
                patch("quantcheck.official_mail_forwarder.deliver_email", return_value=(["ok@example.com"], [])) as deliver,
            ):
                first = forward_official_mail(env)
                second = forward_official_mail(env)

        self.assertEqual(first["forwarded"], 1)
        self.assertEqual(second["forwarded"], 0)
        deliver.assert_called_once()
        self.assertEqual(deliver.call_args.kwargs["to"], ["friend@example.com", "admin@example.com"])

    def test_forwarder_retries_partial_recipient_failure(self):
        msg = EmailMessage()
        msg["From"] = "Quant GT <support@quantgt.io>"
        msg["Subject"] = "Monthly Picks Updated"
        msg["Date"] = "Mon, 25 May 2026 08:00:00 +0000"
        msg.set_content("New monthly picks are available.")

        class FakeImap:
            def select(self, mailbox, readonly=True):
                return "OK", []

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"1"]
                if command == "fetch":
                    return "OK", [(b"1 (RFC822 {1}", msg.as_bytes())]
                raise AssertionError(command)

            def logout(self):
                return "OK", []

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "official_mail_forwarder_state.json"
            env = {
                "OFFICIAL_MAIL_ENABLED": "1",
                "OFFICIAL_MAIL_PROVIDER": "imap",
                "NOTIFY_EMAIL_TO": "friend@example.com",
                "NOTIFY_EMAIL_FILE": "",
                "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
                "NOTIFY_ADMIN_EMAIL_FILE": "",
                "OFFICIAL_MAIL_IMAP_HOST": "imap.example.com",
                "OFFICIAL_MAIL_IMAP_USERNAME": "receiver@example.com",
                "OFFICIAL_MAIL_IMAP_PASSWORD": "secret",
                "OFFICIAL_MAIL_IMAP_SECURITY": "starttls",
            }
            with (
                patch("quantcheck.official_mail_forwarder.STATE_FILE", state_file),
                patch("quantcheck.official_mail_forwarder.connect_imap", return_value=FakeImap()),
                patch("quantcheck.official_mail_forwarder.deliver_email", return_value=(["friend@example.com"], ["admin@example.com"])) as deliver,
            ):
                first = forward_official_mail(env)
                second = forward_official_mail(env)

        self.assertEqual(first["forwarded"], 0)
        self.assertEqual(first["failed"], 1)
        self.assertEqual(second["forwarded"], 0)
        self.assertEqual(deliver.call_count, 2)
        self.assertEqual(deliver.call_args.kwargs["to"], ["friend@example.com", "admin@example.com"])

    def test_send_failure_alert_goes_only_to_admins(self):
        msg = EmailMessage()
        msg["From"] = "Quant GT <support@quantgt.io>"
        msg["Subject"] = "Monthly Picks Updated"
        msg["Date"] = "Mon, 25 May 2026 08:00:00 +0000"
        msg.set_content("New monthly picks are available.")

        class FakeImap:
            def select(self, mailbox, readonly=True):
                return "OK", []

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"1"]
                if command == "fetch":
                    return "OK", [(b"1 (RFC822 {1}", msg.as_bytes())]
                raise AssertionError(command)

            def logout(self):
                return "OK", []

        env = {
            "OFFICIAL_MAIL_ENABLED": "1",
            "OFFICIAL_MAIL_PROVIDER": "imap",
            "NOTIFY_EMAIL_TO": "friend@example.com",
            "NOTIFY_EMAIL_FILE": "",
            "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
            "NOTIFY_ADMIN_EMAIL_FILE": "",
            "OFFICIAL_MAIL_IMAP_HOST": "imap.example.com",
            "OFFICIAL_MAIL_IMAP_USERNAME": "receiver@example.com",
            "OFFICIAL_MAIL_IMAP_PASSWORD": "secret",
            "OFFICIAL_MAIL_IMAP_SECURITY": "starttls",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("quantcheck.official_mail_forwarder.load_env"),
            patch("quantcheck.official_mail_forwarder.connect_imap", return_value=FakeImap()),
            patch("quantcheck.official_mail_forwarder.deliver_email", side_effect=[([], ["friend@example.com", "admin@example.com"]), (["admin@example.com"], [])]) as deliver,
            patch("sys.argv", ["quantcheck-official-mail"]),
        ):
            main()

        self.assertEqual(deliver.call_count, 2)
        self.assertEqual(deliver.call_args_list[0].kwargs["to"], ["friend@example.com", "admin@example.com"])
        self.assertEqual(deliver.call_args_list[1].kwargs["to"], ["admin@example.com"])
        self.assertIn("html", deliver.call_args_list[1].kwargs)
        self.assertIn("Quant GT Monitor", deliver.call_args_list[1].kwargs["html"])
        self.assertIn("Official Mail Forward Failed", deliver.call_args_list[1].kwargs["html"])

    def test_check_failure_alert_goes_only_to_admins(self):
        env = {
            "OFFICIAL_MAIL_ENABLED": "1",
            "OFFICIAL_MAIL_PROVIDER": "imap",
            "NOTIFY_EMAIL_TO": "friend@example.com",
            "NOTIFY_EMAIL_FILE": "",
            "NOTIFY_ADMIN_EMAIL_TO": "admin@example.com",
            "NOTIFY_ADMIN_EMAIL_FILE": "",
            "OFFICIAL_MAIL_IMAP_HOST": "imap.example.com",
            "OFFICIAL_MAIL_IMAP_USERNAME": "receiver@example.com",
            "OFFICIAL_MAIL_IMAP_PASSWORD": "secret",
            "OFFICIAL_MAIL_IMAP_SECURITY": "starttls",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("quantcheck.official_mail_forwarder.load_env"),
            patch("quantcheck.official_mail_forwarder.connect_imap", side_effect=RuntimeError("imap down")),
            patch("quantcheck.official_mail_forwarder.deliver_email", return_value=(["ok@example.com"], [])) as deliver,
            patch("sys.argv", ["quantcheck-official-mail"]),
        ):
            with self.assertRaises(RuntimeError):
                main()

        deliver.assert_called_once()
        self.assertEqual(deliver.call_args.kwargs["to"], ["admin@example.com"])
        self.assertIn("html", deliver.call_args.kwargs)
        self.assertIn("Quant GT Monitor", deliver.call_args.kwargs["html"])
        self.assertIn("Official Mail Check Failed", deliver.call_args.kwargs["html"])


if __name__ == "__main__":
    unittest.main()
