import unittest

from quantcheck.site_diff_notify import diff, screenshot_attachments


class SiteDiffTests(unittest.TestCase):
    def test_capture_failure_suppresses_site_change_alert(self):
        old = {"pages": [{"name": "dashboard", "headings": ["Old"], "nav": [], "buttons": [], "links": []}]}
        new = {"pages": [{"name": "dashboard", "capture_warning": "Timeout"}]}

        self.assertEqual(diff(old, new), [])

    def test_market_tools_noise_is_suppressed(self):
        old = {"pages": [{"name": "market_tools", "headings": ["Tools"], "nav": [], "buttons": [], "links": []}]}
        new = {
            "pages": [
                {
                    "name": "market_tools",
                    "headings": ["Tools", "Breaking news"],
                    "nav": [],
                    "buttons": [],
                    "links": [{"text": "News", "href": "https://www.cnbc.com/story"}],
                }
            ]
        }

        self.assertEqual(diff(old, new), [])


    def test_existing_screenshots_become_email_attachments(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            dash = Path(tmp) / "dashboard.png"
            missing = Path(tmp) / "missing.png"
            dash.write_bytes(b"png")
            snapshot = {"screenshots": {"dashboard": str(dash), "weekly": str(missing)}}

            self.assertEqual(screenshot_attachments(snapshot), [dash])


if __name__ == "__main__":
    unittest.main()
