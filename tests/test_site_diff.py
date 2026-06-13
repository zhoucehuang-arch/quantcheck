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


    def test_news_ticker_links_are_suppressed_but_real_nav_change_surfaces(self):
        old = {
            "pages": [
                {
                    "name": "dashboard",
                    "headings": [],
                    "nav": ["Research NEW"],
                    "buttons": [],
                    "links": [
                        {"text": "Research NEW", "href": "https://quantgt.io/research"},
                        {"text": "BofA Raises SanDisk (SNDK) Price Target 11h ago", "href": "https://finance.yahoo.com/markets/stocks/articles/x"},
                    ],
                }
            ]
        }
        new = {
            "pages": [
                {
                    "name": "dashboard",
                    "headings": [],
                    "nav": ["Quant Research NEW"],
                    "buttons": [],
                    "links": [
                        {"text": "Quant Research NEW", "href": "https://quantgt.io/research"},
                        {"text": "Dow Jones Futures: Stock Market Jumps 7m ago", "href": "https://finance.yahoo.com/m/abc"},
                    ],
                }
            ]
        }

        lines = diff(old, new)
        # The genuine nav rename must surface.
        self.assertIn("dashboard nav added: Quant Research NEW", lines)
        self.assertIn("dashboard nav removed: Research NEW", lines)
        # No news-ticker link (Yahoo Finance / "N ago" timestamps) may appear anywhere.
        joined = "\n".join(lines)
        self.assertNotIn("finance.yahoo.com", joined)
        self.assertNotIn("ago", joined)

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
