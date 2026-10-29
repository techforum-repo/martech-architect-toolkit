"""The signed-in AEM window used for screenshots, against a sample author that
behaves like the real one: its UI trusts only the tab that signed in."""

import time
import unittest
from unittest import mock

from web_inspector import aem_browser, aem_screens
from web_inspector.aem_screens import AemLoginRequired, capture_page_properties
from tests.test_scanner import browser_available

AUTHOR = "https://author-p9-e9.adobeaemcloud.com"
SIGN_IN = "https://auth.services.adobe.com/en_US/index.html"

IMS_TOKEN = "https://ims-na1.adobelogin.com/ims/check/v6/token"

DIALOG = """<!doctype html><html><body>
<script>
  // Like AEM's UI: the Adobe sign-in lives in this tab's storage, and is refreshed
  // with a POST to Adobe's login service; if either fails, go to Adobe sign-in.
  if (!sessionStorage.getItem('adobe-ims')) location.href = '""" + SIGN_IN + """';
  fetch('""" + IMS_TOKEN + """', {method: 'POST'}).then(r => r.ok || Promise.reject())
    .catch(() => { location.href = '""" + SIGN_IN + """'; });
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
            elif request.url.startswith(IMS_TOKEN):
                route.fulfill(status=200, content_type="application/json", body='{"valid": true}')
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
        self.assertIn("POST " + AUTHOR, result["blocked_writes"][0])
        author_posts = [url for method, url in self.seen if method == "POST" and url.startswith(AUTHOR)]
        self.assertEqual(author_posts, [])  # never reached the author

    def test_adobe_sign_in_refresh_is_allowed(self):
        # Blocking this POST is what sent the real author's UI to Adobe sign-in.
        aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
        self.assertIn(("POST", IMS_TOKEN), self.seen)

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


class WriteRuleTests(unittest.TestCase):
    def test_only_writes_to_author_are_blocked(self):
        from web_inspector.aem_screens import blocks_write
        self.assertTrue(blocks_write("POST", AUTHOR + "/libs/granite/csrf/token.json", AUTHOR))
        self.assertTrue(blocks_write("delete", AUTHOR + "/content/site/en", AUTHOR))
        self.assertFalse(blocks_write("GET", AUTHOR + "/content/site/en.html", AUTHOR))
        self.assertFalse(blocks_write("POST", IMS_TOKEN, AUTHOR))
        # A look-alike host is another site, not the author (and can't change author content).
        self.assertFalse(blocks_write("POST", "https://author-p9-e9.adobeaemcloud.com.evil.net/x", AUTHOR))


if __name__ == "__main__":
    unittest.main()


LATE_FORM = """<!doctype html><html><body><script>
  if (!sessionStorage.getItem('adobe-ims')) location.href = '""" + SIGN_IN + """';
  // Like AEM's UI building the form after load, from a request made later.
  setTimeout(() => fetch('/mnt/form.html').then(r => r.text())
    .then(html => { document.body.insertAdjacentHTML('beforeend', html); }), 1500);
</script></body></html>"""


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowLateFormTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        inner = strict_author(self.seen)

        def prepare(context):
            inner(context)

            def late(route):
                self.seen.append((route.request.method, route.request.url))
                if route.request.url.endswith("/mnt/form.html"):
                    body = DIALOG.split("</script>")[1].split("</body>")[0]
                else:
                    body = LATE_FORM
                route.fulfill(status=200, content_type="text/html", body=body)
            context.route(AUTHOR + "/mnt/late/**", late)
            context.route(AUTHOR + "/mnt/form.html", late)

        self.window = aem_browser.open_window("env_late", AUTHOR, show_browser=False,
                                              prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_late")

    def test_form_built_after_load_is_captured(self):
        result = self.window.capture([AUTHOR + "/mnt/late/properties.html"], "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["Analytics domain"])

    def test_page_requests_are_answered_between_captures(self):
        # Don't wait for fields, so the form's request comes after the capture returned.
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            self.window.capture([AUTHOR + "/mnt/late/properties.html"], "tracking.example.com")
        time.sleep(4)
        self.assertTrue(any(url.endswith("/mnt/form.html") for _, url in self.seen))


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowNoticeTests(unittest.TestCase):
    def test_window_shows_a_notice_and_keeps_the_sign_in(self):
        window = aem_browser.open_window("env_notice", AUTHOR, show_browser=False,
                                         prepare_context=strict_author([]), timeout=20)
        self.addCleanup(aem_browser.close_window, "env_notice")
        # The dialog still sees the tab's sign-in after the notice replaced the start page.
        result = aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["Analytics domain"])
