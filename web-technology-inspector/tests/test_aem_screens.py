"""Page Properties capture against a fixture author served through Playwright
routing (no network). Skipped when Chromium isn't installed."""

import unittest

from web_inspector import aem_mock
from web_inspector.aem_screens import (
    AemLoginRequired,
    SignInIncomplete,
    _is_sign_in_page,
    capture_component_dialog,
    capture_page_properties,
    component_dialog_urls,
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
        for url in ("https://ims-na1.adobelogin.com/ims/authorize",
                    "https://auth.services.adobe.com/en_US/index.html",  # seen on a real author
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


class ComponentDialogUrlTests(unittest.TestCase):
    def test_relative_resource_type_tries_apps_then_libs(self):
        self.assertEqual(component_dialog_urls(AUTHOR, "/content/site/en/jcr:content/root/embed",
                                               "core/wcm/components/embed/v2/embed"), [
            AUTHOR + "/mnt/override/apps/core/wcm/components/embed/v2/embed/_cq_dialog.html"
                     "/content/site/en/jcr:content/root/embed",
            AUTHOR + "/mnt/override/libs/core/wcm/components/embed/v2/embed/_cq_dialog.html"
                     "/content/site/en/jcr:content/root/embed",
        ])

    def test_absolute_resource_type_keeps_its_root_first(self):
        urls = component_dialog_urls(AUTHOR, "/content/x", "/libs/wcm/foundation/components/text")
        self.assertIn("/mnt/override/libs/wcm/foundation/components/text/_cq_dialog.html/content/x", urls[0])
        self.assertIn("/mnt/override/apps/", urls[1])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class ComponentDialogCaptureTests(unittest.TestCase):
    AUTHOR = aem_mock.ENVIRONMENT["author_base"]
    EMBED = "/content/example/us/en/products/jcr:content/root/container/embed"

    def test_component_dialog_field_captured(self):
        state = sign_in(self.AUTHOR, show_browser=False, prepare_context=aem_mock.serve_author_ui)
        result = capture_component_dialog(self.AUTHOR, self.EMBED, "core/wcm/components/embed/v2/embed",
                                          "tracking.example.com", None, storage_state=state,
                                          prepare_context=aem_mock.serve_author_ui)
        self.assertEqual([f["label"] for f in result["fields"]], ["html"])
        self.assertIn("/mnt/override/apps/", result["url"])

    def test_falls_back_to_libs_when_apps_has_no_dialog(self):
        def libs_only(context):
            def handle(route):
                url = route.request.url
                if "/mnt/override/apps/" in url:
                    route.fulfill(status=404, body="not found")
                elif "/mnt/override/libs/" in url:
                    route.fulfill(status=200, content_type="text/html", body=(
                        "<div class='coral-Form-fieldwrapper'><label>HTML</label>"
                        "<input name='./html' value='https://tracking.example.com/t.js'></div>"))
                else:
                    route.fulfill(status=200, body=b"")
            context.route("**/*", handle)
        result = capture_component_dialog(AUTHOR, "/content/site/en/jcr:content/root/embed",
                                          "core/wcm/components/embed/v2/embed", "tracking.example.com", TOKEN,
                                          prepare_context=libs_only)
        self.assertIn("/mnt/override/libs/", result["url"])
        self.assertEqual([f["label"] for f in result["fields"]], ["HTML"])

    def test_screenshots_reuse_the_sign_in_browser_identity(self):
        agents = []

        def record(context):
            def handle(route):
                agents.append(route.request.headers.get("user-agent"))
                route.fallback()
            aem_mock.serve_author_ui(context)
            context.route("**/*", handle)  # registered after: sees requests first

        state = dict(sign_in(self.AUTHOR, show_browser=False, prepare_context=aem_mock.serve_author_ui),
                     user_agent="SignInBrowser/1.0")
        capture_page_properties(self.AUTHOR, "/content/example/us/en", "tracking.example.com", None,
                                storage_state=state, prepare_context=record)
        self.assertTrue(agents)
        self.assertEqual(set(agents), {"SignInBrowser/1.0"})

    def test_no_session_uses_a_non_headless_agent(self):
        agents = []

        def record(context):
            def handle(route):
                agents.append(route.request.headers.get("user-agent"))
                route.fulfill(status=200, content_type="text/html", body="<p>dialog</p>")
            context.route("**/*", handle)
        capture_page_properties(AUTHOR, "/content/site/en", "x", TOKEN, prepare_context=record)
        self.assertTrue(agents and not any("Headless" in a for a in agents))


if __name__ == "__main__":
    unittest.main()


NESTED_DIALOG = """<!doctype html><html><body>
<coral-tabview id="outer">
  <coral-tablist><coral-tab>Basic</coral-tab><coral-tab>Analytics</coral-tab></coral-tablist>
  <coral-panelstack>
    <coral-panel><div class="coral-Form-fieldwrapper"><label>Title</label><input name="./jcr:title" value="Home"></div></coral-panel>
    <coral-panel>
      <coral-tabview id="inner">
        <coral-tablist><coral-tab>General</coral-tab><coral-tab id="tab-tracking">Tracking</coral-tab></coral-tablist>
        <coral-panelstack>
          <coral-panel><div class="coral-Form-fieldwrapper"><label>Owner</label><input name="./owner" value="x"></div></coral-panel>
          <coral-panel aria-labelledby="tab-tracking"><div class="coral-Form-fieldwrapper"><label>Tracking domain</label>
            <input name="./trackingDomain" value="tracking.example.com"></div></coral-panel>
        </coral-panelstack>
      </coral-tabview>
    </coral-panel>
  </coral-panelstack>
</coral-tabview>
<script>
  // Coral-like behaviour: a tab shows the panel at its position in its own tab view.
  document.querySelectorAll('coral-tabview').forEach(view => {
    const tabs = [...view.querySelector(':scope > coral-tablist').children];
    const panels = [...view.querySelector(':scope > coral-panelstack').children];
    const show = i => panels.forEach((p, n) => { p.style.display = n === i ? '' : 'none'; p.toggleAttribute('selected', n === i); });
    tabs.forEach((tab, i) => tab.addEventListener('click', () => show(i)));
    show(0);
  });
</script></body></html>"""


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class NestedTabTests(unittest.TestCase):
    def test_field_on_nested_custom_tab(self):
        def serve(context):
            context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html",
                                                              body=NESTED_DIALOG))
        result = capture_page_properties(AUTHOR, "/content/site/en", "tracking.example.com", TOKEN,
                                         prepare_context=serve)
        [field] = result["fields"]
        self.assertEqual(field["label"], "Tracking domain")
        self.assertEqual(field["tabs"], ["Analytics", "Tracking"])  # outer tab, then the custom inner tab
        self.assertTrue(field["visible"])  # both tabs were opened, so the field is on screen
        self.assertTrue(field["image"].startswith(b"\x89PNG"))
