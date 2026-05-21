import unittest

from quantcheck.site_diff_notify import diff


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


if __name__ == "__main__":
    unittest.main()
