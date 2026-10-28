"""Runs the real scanner in Chromium against fixture pages served by Playwright
routing, so no network is used. Skipped when the browser isn't installed."""

import unittest

from web_inspector.scanner import BLOCK_PAGE_TITLE, ScanBlocked, _desktop_user_agent, scan

SITE = "https://www.example.test"

PAGE = """<!doctype html><html><head><title>Fixture</title>
<script src="https://vendor.example.net/early.js"></script>
<script>window.adobeDataLayer = [];</script></head>
<body style="height:3000px">
<div id="onetrust-banner-sdk"><button id="onetrust-accept-btn-handler"
  onclick="document.cookie='consent=yes;path=/'; var s=document.createElement('script');
  s.src='https://vendor.example.net/after-consent.js'; document.head.appendChild(s);">Accept</button></div>
<img src="https://vendor.example.net/redirect">
</body></html>"""


def serve(context):
    def handle(route):
        url = route.request.url
        if url == SITE + "/page.html":
            route.fulfill(status=200, content_type="text/html", body=PAGE,
                          headers={"Set-Cookie": "session=1; Path=/"})
        elif url.endswith("/redirect"):
            route.fulfill(status=302, headers={"Location": "https://vendor.example.net/pixel.gif"})
        elif url.endswith(".gif"):
            route.fulfill(status=200, content_type="image/gif", body=b"GIF89a")
        elif url.endswith("/blocked.html"):
            route.fulfill(status=403, content_type="text/html", body="<title>Access Denied</title>")
        else:
            route.fulfill(status=200, content_type="application/javascript", body="window.loaded=1;")
    context.route("**/*", handle)


def browser_available():
    try:
        scan(SITE + "/page.html", settle=1, prepare_context=serve)
        return True
    except Exception as exc:  # noqa: BLE001
        return "Executable doesn't exist" not in str(exc) and _raise(exc)


def _raise(exc):
    raise exc


class ScannerHelperTests(unittest.TestCase):
    def test_user_agent_is_not_headless(self):
        agent = _desktop_user_agent("156.0.8078.4")
        self.assertIn("Chrome/156.0.0.0", agent)
        self.assertNotIn("Headless", agent)

    def test_block_titles(self):
        for title in ("Access Denied", "Attention Required! | Cloudflare", "Just a moment..."):
            self.assertTrue(BLOCK_PAGE_TITLE.search(title))
        self.assertFalse(BLOCK_PAGE_TITLE.search("Products | Example"))


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class ScannerBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(SITE + "/page.html", consent="accept", settle=1, prepare_context=serve)

    def by_url(self, suffix):
        return [r for r in self.result["requests"] if r["url"].endswith(suffix)]

    def test_consent_splits_requests(self):
        self.assertEqual(self.result["consent"], {"mode": "accept", "platform": "OneTrust", "accepted": True})
        self.assertEqual(self.by_url("early.js")[0]["phase"], "before_consent")
        self.assertEqual(self.by_url("after-consent.js")[0]["phase"], "after_consent")

    def test_consent_splits_cookies(self):
        before = {c["name"] for c in self.result["cookies_before_consent"]}
        after = {c["name"] for c in self.result["cookies"]}
        self.assertEqual(before, {"session"})
        self.assertEqual(after, {"session", "consent"})

    def test_redirect_hop_is_kept(self):
        hop = self.by_url("/redirect")[0]
        self.assertEqual(hop["status"], 302)
        self.assertEqual(hop["redirected_to"], "https://vendor.example.net/pixel.gif")
        self.assertEqual(self.by_url("pixel.gif")[0]["redirect_from"], "https://vendor.example.net/redirect")

    def test_globals_cookies_and_screenshot(self):
        self.assertIn("adobeDataLayer", self.result["globals"])
        self.assertTrue(self.result["screenshot"].startswith(b"\x89PNG"))
        self.assertNotIn("Headless", self.result["user_agent"])

    def test_mobile_device(self):
        result = scan(SITE + "/page.html", device="mobile", settle=1, prepare_context=serve)
        self.assertIn("Mobile", result["user_agent"])
        self.assertEqual(result["consent"]["mode"], "none")
        self.assertEqual({r["phase"] for r in result["requests"]}, {"page_load"})

    def test_blocked_site(self):
        with self.assertRaises(ScanBlocked):
            scan(SITE + "/blocked.html", settle=1, prepare_context=serve)


if __name__ == "__main__":
    unittest.main()
