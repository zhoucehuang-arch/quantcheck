import unittest

from quantcheck import picks_report


class FakeLocator:
    def count(self):
        return 0


class FakeContext:
    def cookies(self, base):
        return [{"name": "__Secure-authjs.session-token"}]


class FakePage:
    context = FakeContext()

    def locator(self, selector):
        return FakeLocator()

    def get_by_role(self, role, name=None):
        return FakeLocator()

    def evaluate(self, script):
        if "subscription" in script.lower():
            return True
        return True


class PageValidationTests(unittest.TestCase):
    def test_subscription_gate_is_rejected_even_with_auth_cookie_and_pick_text(self):
        with self.assertRaisesRegex(RuntimeError, "subscription/paywall"):
            picks_report.assert_authenticated_page(FakePage(), "weekly")


if __name__ == "__main__":
    unittest.main()
