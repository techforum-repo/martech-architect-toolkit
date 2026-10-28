"""The signed-in AEM window used for screenshots, against a sample author that
behaves like the real one: its UI trusts only the tab that signed in."""

import unittest

from web_inspector import aem_browser
from web_inspector.aem_screens import AemLoginRequired, capture_page_properties
from tests.test_scanner import browser_available

AUTHOR = "https://author-p9-e9.adobeaemcloud.com"
SIGN_IN = "https://auth.services.adobe.com/en_US/index.html"

DIALOG = """<!doctype html><html><body>
<script>
  // Like AEM's UI: the Adobe sign-in lives in this tab's storage; without it, go to Adobe sign-in.
  if (!sessionStorage.getItem('adobe-ims')) location.href = '""" + SIGN_IN + """';
  fetch('/libs/granite/csrf/token.json', {method: 'POST'}).catch(() => {});
</script>
<div class="coral-Form-fieldwrapper"><label>Analytics domain</label>
<input name="./analyticsDomain" value="tracking.example.com"></div></body></html>"""


def strict_author(seen):
    def prepare(context):
        def handle(route):
            request = route.request
            seen.append((request.method, request.url))
            if request.url.startswith(AUTHOR + "/aem/start.html"):
                route.fulfill(status=200, content_type="text/html", headers={"Set-Cookie": "login-token=t; Path=/; Secure"},
                              body="<script>sessionStorage.setItem('adobe-ims', 'signed-in')</script>Start")
            elif request.url.startswith(AUTHOR + "/mnt/"):
                route.fulfill(status=200, content_type="text/html", body=DIALOG)
            elif request.url.startswith(SIGN_IN):
                route.fulfill(status=200, content_type="text/html", body="<title>Sign in</title>")
            else:
                route.fulfill(status=200, body=b"")
        context.route("**/*", handle)
    return prepare


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.window = aem_browser.open_window("env_test", AUTHOR, show_browser=False,
                                              prepare_context=strict_author(self.seen), timeout=20)
        self.addCleanup(aem_browser.close_window, "env_test")

    def test_screenshot_works_in_the_signed_in_window(self):
        result = aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["Analytics domain"])
        self.assertTrue(result["fields"][0]["visible"])

    def test_a_new_browser_is_sent_to_adobe_sign_in(self):
        # What happened on the real author before: the copied cookies aren't enough.
        with self.assertRaises(AemLoginRequired) as raised:
            capture_page_properties(AUTHOR, "/content/site/en", "tracking.example.com", None,
                                    storage_state=self.window.storage_state,
                                    prepare_context=strict_author([]))
        self.assertTrue(raised.exception.sign_in_page)

    def test_window_is_read_only_after_sign_in(self):
        result = aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
        self.assertEqual(len(result["blocked_writes"]), 1)
        self.assertIn("POST", result["blocked_writes"][0])
        self.assertNotIn("POST", {method for method, _ in self.seen})  # never reached the author

    def test_several_captures_and_reruns_share_the_window(self):
        self.assertIs(aem_browser.get_window("env_test"), self.window)
        for _ in range(2):
            result = aem_browser.capture_component_dialog(self.window, "/content/site/en/jcr:content/root/embed",
                                                          "core/wcm/components/embed/v2/embed", "tracking.example.com")
            self.assertEqual(len(result["fields"]), 1)

    def test_closed_window(self):
        aem_browser.close_window("env_test")
        self.assertIsNone(aem_browser.get_window("env_test"))
        with self.assertRaises(aem_browser.WindowClosed):
            self.window.capture([AUTHOR + "/mnt/x"], "x", timeout=5)


if __name__ == "__main__":
    unittest.main()
