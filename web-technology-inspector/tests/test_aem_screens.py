"""Dialog screenshots in the signed-in AEM window, against fixture authors
served through Playwright routing (no network). Skipped when Chromium isn't
installed."""

import unittest

from web_inspector import aem_browser, aem_mock
from web_inspector.aem_screens import (
    AemLoginRequired,
    SignInIncomplete,
    _is_sign_in_page,
    component_dialog_urls,
    properties_url,
)
from tests.test_scanner import browser_available

AUTHOR = "https://author-p1-e2.adobeaemcloud.com"

DIALOG = """<!doctype html><html><head><title>Page Properties</title></head><body>
<coral-tablist><coral-tab onclick="show(0)">Basic</coral-tab><coral-tab onclick="show(1)">Advanced</coral-tab></coral-tablist>
<coral-panelstack>
  <coral-panel><div class="coral-Form-fieldwrapper"><label>Title</label><input name="./jcr:title" value="Products"></div></coral-panel>
  <coral-panel style="display:none"><div class="coral-Form-fieldwrapper"><label>Analytics domain</label>
    <input name="./analyticsDomain" value="https://tracking.example.com/t.js"></div></coral-panel>
</coral-panelstack>
<script>
  function show(i) { document.querySelectorAll('coral-panel').forEach((p, n) => p.style.display = n === i ? '' : 'none'); }
</script></body></html>"""

LIBS_DIALOG = ("<div class='coral-Form-fieldwrapper'><label>HTML</label>"
               "<input name='./html' value='https://tracking.example.com/t.js'></div>")

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


def author(serve):
    """A fixture author: the start page signs in, serve(route) answers the rest."""
    def prepare(context):
        def handle(route):
            if route.request.url.startswith(AUTHOR + "/aem/start.html"):
                route.fulfill(status=200, content_type="text/html",
                              headers={"Set-Cookie": "login-token=t; Path=/; Secure"}, body="Start")
            else:
                serve(route)
        context.route("**/*", handle)
    return prepare


def html(body, status=200):
    return lambda route: route.fulfill(status=status, content_type="text/html", body=body)


class UrlTests(unittest.TestCase):
    def test_sign_in_page_detection(self):
        self.assertTrue(_is_sign_in_page("https://auth.services.adobe.com/en_US/index.html"))
        self.assertTrue(_is_sign_in_page("https://ims-na1.adobelogin.com/ims/authorize"))
        self.assertTrue(_is_sign_in_page(AUTHOR + "/libs/granite/core/content/login.html"))
        # The page being opened is in the query string, so its path never decides it.
        self.assertFalse(_is_sign_in_page(properties_url(AUTHOR, "/content/site/login/en")))
        self.assertFalse(_is_sign_in_page(properties_url(AUTHOR, "/content/oauth-demo/en")))

    def test_relative_resource_type_tries_apps_then_libs(self):
        urls = component_dialog_urls(AUTHOR, "/content/site/en/jcr:content/root/embed",
                                     "core/wcm/components/embed/v2/embed")
        self.assertEqual(urls, [
            AUTHOR + "/mnt/override/apps/core/wcm/components/embed/v2/embed/_cq_dialog.html"
                     "/content/site/en/jcr:content/root/embed",
            AUTHOR + "/mnt/override/libs/core/wcm/components/embed/v2/embed/_cq_dialog.html"
                     "/content/site/en/jcr:content/root/embed",
        ])

    def test_absolute_resource_type_keeps_its_root_first(self):
        urls = component_dialog_urls(AUTHOR, "/content/x/jcr:content/c", "/libs/wcm/foundation/components/text")
        self.assertIn("/mnt/override/libs/wcm/foundation/components/text/_cq_dialog.html", urls[0])
        self.assertIn("/mnt/override/apps/", urls[1])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class CaptureTests(unittest.TestCase):
    def window(self, prepare):
        window = aem_browser.open_window("env_screens", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_screens")
        return window

    def test_field_on_second_tab_is_captured(self):
        window = self.window(author(html(DIALOG)))
        result = aem_browser.capture_page_properties(window, "/content/site/us/en/products", "tracking.example.com")
        [field] = result["fields"]
        self.assertEqual((field["label"], field["tabs"]), ("Analytics domain", ["Advanced"]))
        self.assertTrue(field["visible"])
        self.assertTrue(field["image"].startswith(b"\x89PNG"))

    def test_no_match_returns_dialog_screenshot(self):
        window = self.window(author(html(DIALOG)))
        result = window.capture([properties_url(AUTHOR, "/content/site/en")], "nothing-like-this", timeout=30)
        self.assertEqual(result["fields"], [])
        self.assertTrue(result["page_image"].startswith(b"\x89PNG"))

    def test_login_redirect_is_reported(self):
        to_sign_in = "<script>location.href='https://ims-na1.adobelogin.com/ims/login'</script>"

        def serve(route):
            if "adobelogin.com" in route.request.url:
                html("<title>Sign in</title>")(route)
            else:
                html(to_sign_in)(route)
        window = self.window(author(serve))
        with self.assertRaises(AemLoginRequired) as raised:
            aem_browser.capture_page_properties(window, "/content/site/en", "x")
        self.assertTrue(raised.exception.sign_in_page)

    def test_redirect_elsewhere_is_not_a_sign_in(self):
        shell = "https://experience.adobe.com/#/aem"

        def serve(route):
            if route.request.url.startswith("https://experience.adobe.com"):
                html("<title>Experience Cloud</title>")(route)
            else:
                html(f"<script>location.href='{shell}'</script>")(route)
        window = self.window(author(serve))
        with self.assertRaises(AemLoginRequired) as raised:
            aem_browser.capture_page_properties(window, "/content/site/en", "x")
        self.assertFalse(raised.exception.sign_in_page)

    def test_field_on_nested_custom_tab(self):
        window = self.window(author(html(NESTED_DIALOG)))
        [field] = aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")["fields"]
        self.assertEqual(field["label"], "Tracking domain")
        self.assertEqual(field["tabs"], ["Analytics", "Tracking"])  # outer tab, then the custom inner tab
        self.assertTrue(field["visible"])  # both tabs were opened, so the field is on screen

    def test_component_dialog_falls_back_to_libs_when_apps_answers_500(self):
        def serve(route):
            if "/mnt/override/apps/" in route.request.url:
                route.fulfill(status=500, body="Internal Server Error")
            else:
                html(LIBS_DIALOG)(route)
        window = self.window(author(serve))
        result = aem_browser.capture_component_dialog(window, "/content/site/en/jcr:content/root/embed",
                                                      "core/wcm/components/embed/v2/embed", "tracking.example.com")
        self.assertEqual([a["status"] for a in result["attempts"]], [500, 200])
        self.assertIn("/mnt/override/libs/", result["url"])
        self.assertEqual([f["label"] for f in result["fields"]], ["HTML"])

    def test_component_dialog_falls_back_to_libs_when_apps_has_no_dialog(self):
        def serve(route):
            if "/mnt/override/apps/" in route.request.url:
                route.fulfill(status=404, body="not found")
            else:
                html(LIBS_DIALOG)(route)
        window = self.window(author(serve))
        result = aem_browser.capture_component_dialog(window, "/content/site/en/jcr:content/root/embed",
                                                      "core/wcm/components/embed/v2/embed", "tracking.example.com")
        self.assertIn("/mnt/override/libs/", result["url"])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class MockAuthorTests(unittest.TestCase):
    """The sample author used in mock mode, through the same window."""
    AUTHOR = aem_mock.ENVIRONMENT["author_base"]

    def setUp(self):
        self.window = aem_browser.open_window("env_mock", self.AUTHOR, show_browser=False,
                                              prepare_context=aem_mock.serve_author_ui, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_mock")

    def test_page_properties(self):
        result = aem_browser.capture_page_properties(self.window, "/content/example/us/en", "tracking.example.com")
        self.assertTrue(result["fields"])

    def test_component_dialog(self):
        result = aem_browser.capture_component_dialog(
            self.window, "/content/example/us/en/products/jcr:content/root/container/embed",
            "core/wcm/components/embed/v2/embed", "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["html"])
        self.assertIn("/mnt/override/apps/", result["url"])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class SignInTimeoutTests(unittest.TestCase):
    def test_sign_in_times_out(self):
        never = lambda context: context.route("**/*", html("<title>Sign in</title>"))  # noqa: E731
        with self.assertRaises(SignInIncomplete):
            aem_browser.open_window("env_never", AUTHOR, show_browser=False, prepare_context=never, timeout=2)


if __name__ == "__main__":
    unittest.main()
