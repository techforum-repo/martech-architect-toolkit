"""Page Properties capture against a fixture author served through Playwright
routing (no network). Skipped when Chromium isn't installed."""

import unittest

from web_inspector import aem_mock
from web_inspector.aem_screens import (
    AemLoginRequired,
    SignInIncomplete,
    capture_page_properties,
    properties_url,
    sign_in,
)
from tests.test_scanner import browser_available

AUTHOR = "https://author-p1-e2.adobeaemcloud.com"
TOKEN = "test-token-123"

DIALOG = """<!doctype html><html><head><title>Page Properties</title></head><body>
<coral-tablist><coral-tab onclick="show(0)">Basic</coral-tab><coral-tab onclick="show(1)">Advanced</coral-tab></coral-tablist>
<coral-panelstack>
  <coral-panel><div class="coral-Form-fieldwrapper"><label>Title</label><input name="./jcr:title" value="Products"></div></coral-panel>
  <coral-panel style="display:none"><div class="coral-Form-fieldwrapper"><label>Analytics domain</label>
    <input name="./analyticsDomain" value="https://tracking.example.com/t.js"></div></coral-panel>
</coral-panelstack>
<img src="https://cdn.adobe-ui.example/logo.png">
<script>
  function show(i) { document.querySelectorAll('coral-panel').forEach((p, n) => p.style.display = n === i ? '' : 'none');
                     document.body.setAttribute('data-tab', i); }
  // Background write a real author UI might make; must never reach AEM.
  fetch('/libs/granite/csrf/token.json', {method: 'POST'}).catch(() => {});
</script></body></html>"""


def fixture(seen, login=False):
    def prepare(context):
        def handle(route):
            request = route.request
            seen.append((request.method, request.url, request.headers.get("authorization")))
            if request.url.startswith(AUTHOR + "/mnt/overlay") and login:
                route.fulfill(status=200, content_type="text/html",
                              body="<script>location.href='https://ims.example.test/ims/login'</script>")
            elif request.url.startswith(AUTHOR + "/mnt/overlay"):
                route.fulfill(status=200, content_type="text/html", body=DIALOG)
            elif "ims.example.test" in request.url:
                route.fulfill(status=200, content_type="text/html", body="<title>Sign in</title>")
            else:
                route.fulfill(status=200, body=b"")
        context.route("**/*", handle)
    return prepare


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class PagePropertiesCaptureTests(unittest.TestCase):
    def test_field_on_second_tab_is_captured(self):
        seen = []
        result = capture_page_properties(AUTHOR, "/content/site/us/en/products", "tracking.example.com", TOKEN,
                                         prepare_context=fixture(seen))
        self.assertEqual(result["url"], properties_url(AUTHOR, "/content/site/us/en/products"))
        self.assertEqual([(f["label"], f["name"]) for f in result["fields"]],
                         [("Analytics domain", "./analyticsDomain")])
        self.assertTrue(result["fields"][0]["image"].startswith(b"\x89PNG"))

    def test_read_only_and_token_scoped(self):
        seen = []
        result = capture_page_properties(AUTHOR, "/content/site/us/en/products", "tracking.example.com", TOKEN,
                                         prepare_context=fixture(seen))
        self.assertEqual(len(result["blocked_writes"]), 1)
        self.assertIn("POST", result["blocked_writes"][0])
        self.assertTrue(all(method in ("GET", "HEAD", "OPTIONS") for method, _, _ in seen))  # never reached
        author = {auth for _, url, auth in seen if url.startswith(AUTHOR)}
        others = {auth for _, url, auth in seen if not url.startswith(AUTHOR)}
        self.assertEqual(author, {"Bearer " + TOKEN})
        self.assertTrue(others)
        self.assertEqual(others, {None})  # the token never leaves the author origin

    def test_no_match_returns_dialog_screenshot(self):
        result = capture_page_properties(AUTHOR, "/content/site/us/en/products", "nothing-like-this", TOKEN,
                                         prepare_context=fixture([]))
        self.assertEqual(result["fields"], [])
        self.assertTrue(result["page_image"].startswith(b"\x89PNG"))

    def test_login_redirect_is_reported(self):
        with self.assertRaises(AemLoginRequired) as raised:
            capture_page_properties(AUTHOR, "/content/site/us/en/products", "x", TOKEN,
                                    prepare_context=fixture([], login=True))
        self.assertTrue(raised.exception.sign_in_page)
        self.assertEqual(raised.exception.landed, "https://ims.example.test/ims/login")

    def test_redirect_elsewhere_is_not_a_sign_in(self):
        def shell(context):
            def handle(route):
                if route.request.url.startswith(AUTHOR):
                    route.fulfill(status=200, content_type="text/html",
                                  body="<script>location.href='https://experience.example.test/#/aem/sites'</script>")
                else:
                    route.fulfill(status=200, content_type="text/html", body="<title>Experience Cloud</title>")
            context.route("**/*", handle)
        with self.assertRaises(AemLoginRequired) as raised:
            capture_page_properties(AUTHOR, "/content/site/us/en/products", "x", TOKEN, prepare_context=shell)
        self.assertFalse(raised.exception.sign_in_page)
        self.assertEqual((raised.exception.landed, raised.exception.title),
                         ("https://experience.example.test/#/aem/sites", "Experience Cloud"))

    def test_sign_in_page_detection(self):
        from web_inspector.aem_screens import _is_sign_in_page
        for url in ("https://ims-na1.adobelogin.com/ims/authorize",
                    AUTHOR + "/libs/granite/core/content/login.html", AUTHOR + "/j_security_check"):
            self.assertTrue(_is_sign_in_page(url), url)
        for url in (AUTHOR + "/mnt/overlay/wcm/core/content/sites/properties.html?item=/content/site/login",
                    "https://author-p1-e2.adobeaemcloud.com/aem/start.html"):
            self.assertFalse(_is_sign_in_page(url), url)


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class SignInTests(unittest.TestCase):
    """The sample author: UI pages need its login cookie, the token alone is not enough."""
    AUTHOR = aem_mock.ENVIRONMENT["author_base"]

    def capture(self, **kwargs):
        return capture_page_properties(self.AUTHOR, "/content/example/us/en", "tracking.example.com",
                                       prepare_context=aem_mock.serve_author_ui, **kwargs)

    def test_token_alone_reaches_sign_in_page(self):
        with self.assertRaises(AemLoginRequired):
            self.capture(token="t")

    def test_sign_in_session_is_reused_for_screenshots(self):
        state = sign_in(self.AUTHOR, show_browser=False, prepare_context=aem_mock.serve_author_ui)
        self.assertIn("login-token", {c["name"] for c in state["cookies"]})
        result = self.capture(token=None, storage_state=state)
        self.assertEqual([f["label"] for f in result["fields"]], ["analyticsTrackingDomain"])

    def test_sign_in_times_out(self):
        def never_signed_in(context):
            context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html",
                                                              body="<title>Sign in</title>"))
        with self.assertRaises(SignInIncomplete):
            sign_in(self.AUTHOR, timeout=2, show_browser=False, prepare_context=never_signed_in)


if __name__ == "__main__":
    unittest.main()
