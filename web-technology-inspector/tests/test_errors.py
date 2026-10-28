import unittest

from web_inspector.errors import friendly_error
from web_inspector.scanner import ScanBlocked


class ErrorTests(unittest.TestCase):
    def test_blocked_suggests_show_browser(self):
        error = friendly_error(ScanBlocked("The website answered with 'Access Denied' (HTTP 403)"))
        self.assertIn("blocked", error.title)
        self.assertTrue(any("Show browser" in r for r in error.reasons))

    def test_http2_reset_treated_as_blocking(self):
        error = friendly_error(RuntimeError("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://x"))
        self.assertIn("dropped the connection", error.title)

    def test_missing_browser(self):
        error = friendly_error(RuntimeError("Executable doesn't exist at /x/chrome"))
        self.assertFalse(error.retryable)

    def test_unknown_error_keeps_message(self):
        self.assertIn("KeyError", friendly_error(KeyError("x")).reasons[0])


if __name__ == "__main__":
    unittest.main()
