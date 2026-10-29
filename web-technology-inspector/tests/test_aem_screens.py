"""Dialog screenshots in the signed-in AEM window, against fixture authors
served through Playwright routing (no network). Skipped when Chromium isn't
installed."""

import unittest

from web_inspector import aem_browser, aem_mock
from web_inspector.aem_screens import (
    AemLoginRequired,
    DialogNotOpened,
    SignInIncomplete,
    _is_sign_in_page,
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

EMBED = "/content/site/en/jcr:content/root/container/embed"

# A page editor like AEM's: components load through its editor API, which
# opens a component's dialog in the editor page itself. The side panel also
# shows the value (e.g. in a content tree), which mustn't count as a match.
EDITOR = """<!doctype html><html><body>
<div id="SidePanel"><coral-tablist><coral-tab selected>Content tree</coral-tab></coral-tablist>
  <input name="search" value="tracking.example.com"></div>
<div class="cq-Overlay" data-path="%(path)s" style="width:200px;height:40px;background:#eee">Embed</div>
<script>
  const DIALOG = `<coral-dialog class="is-open" style="display:block">
    <coral-tablist><coral-tab onclick="show(0)">Properties</coral-tab><coral-tab onclick="show(1)">Scripts</coral-tab></coral-tablist>
    <coral-panelstack>
      <coral-panel><div class="coral-Form-fieldwrapper"><label>Title</label><input name="./jcr:title" value="Embed"></div></coral-panel>
      <coral-panel style="display:none"><div class="coral-Form-fieldwrapper"><label>analyticsJS</label>
        <textarea name="./analyticsJS">&lt;script src="https://tracking.example.com/t.js"&gt;&lt;/script&gt;</textarea></div></coral-panel>
    </coral-panelstack></coral-dialog>`;
  const open = () => document.body.insertAdjacentHTML('beforeend', DIALOG);
  function show(i) { document.querySelectorAll('coral-dialog coral-panel').forEach((p, n) => p.style.display = n === i ? '' : 'none'); }
  setTimeout(() => {  // the editor loads its components after the page
    window.Granite = {author: {
      editables: Object.assign([{path: '%(path)s'}], {find(p) { return this.filter(e => e.path === p); }}),
      layerManager: {layer: 'Preview', getCurrentLayerName() { return this.layer; }, activateLayer(n) { this.layer = n; }},
      %(api)s
    }};
  }, 300);
  %(wrench)s
</script></body></html>"""

EDITOR_API = """edit: {Dialog: function (e) { this.editable = e; }},
      DialogFrame: {openDialog(d) { if (Granite.author.layerManager.layer !== 'Edit') throw 'preview'; open(); }},"""

# No usable editor API: select the component, then the wrench, as an author would.
EDITOR_WRENCH = """document.querySelector('.cq-Overlay').addEventListener('click', () => {
    document.body.insertAdjacentHTML('beforeend', '<button data-action="CONFIGURE">Configure</button>');
    document.querySelector('[data-action=CONFIGURE]').addEventListener('click', open);
  });"""

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


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class ComponentDialogTests(unittest.TestCase):
    def window(self, editor):
        def serve(route):
            if route.request.url.startswith(AUTHOR + "/editor.html/content/site/en.html"):
                html(editor)(route)
            else:
                route.fulfill(status=404, body="")
        window = aem_browser.open_window("env_editor", AUTHOR, show_browser=False,
                                         prepare_context=author(serve), timeout=20)
        self.addCleanup(aem_browser.close_window, "env_editor")
        return window

    def test_dialog_opened_through_the_editor_api(self):
        window = self.window(EDITOR % {"path": EMBED, "api": EDITOR_API, "wrench": ""})
        result = aem_browser.capture_component_dialog(window, EMBED, "tracking.example.com")
        [field] = result["fields"]  # the side panel's copy isn't in the dialog, so isn't a match
        self.assertEqual((field["label"], field["tabs"]), ("analyticsJS", ["Scripts"]))
        self.assertTrue(field["visible"])
        self.assertEqual(result["url"], AUTHOR + "/editor.html/content/site/en.html")

    def test_dialog_opened_with_the_wrench_without_the_api(self):
        window = self.window(EDITOR % {"path": EMBED, "api": "", "wrench": EDITOR_WRENCH})
        [field] = aem_browser.capture_component_dialog(window, EMBED, "tracking.example.com")["fields"]
        self.assertEqual(field["tabs"], ["Scripts"])

    def test_component_missing_from_the_editor_is_explained(self):
        window = self.window(EDITOR % {"path": "/content/site/en/jcr:content/other", "api": EDITOR_API,
                                       "wrench": ""})
        with self.assertRaises(DialogNotOpened) as raised:
            aem_browser.capture_component_dialog(window, EMBED, "tracking.example.com")
        self.assertIn("no editable component", str(raised.exception))


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
            "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["html"])
        self.assertIn("/editor.html/content/example/us/en/products.html", result["url"])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class SignInTimeoutTests(unittest.TestCase):
    def test_sign_in_times_out(self):
        never = lambda context: context.route("**/*", html("<title>Sign in</title>"))  # noqa: E731
        with self.assertRaises(SignInIncomplete):
            aem_browser.open_window("env_never", AUTHOR, show_browser=False, prepare_context=never, timeout=2)


if __name__ == "__main__":
    unittest.main()
