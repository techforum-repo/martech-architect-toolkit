"""The signed-in AEM window used for screenshots, against a sample author that
behaves like the real one: its UI trusts only the tab that signed in."""

import time
import unittest
from unittest import mock

from web_inspector import aem_browser, aem_screens
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
  // AEM's UI also POSTs while loading; that must still reach the author.
  fetch('/mnt/overlay/granite/ui/content/load.json', {method: 'POST'});
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

    def test_window_is_read_only_after_sign_in(self):
        result = aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
        self.assertEqual(len(result["blocked_writes"]), 1)
        self.assertIn("POST " + AUTHOR, result["blocked_writes"][0])
        author_posts = [url for method, url in self.seen if method == "POST" and url.startswith(AUTHOR)]
        self.assertEqual(author_posts, [AUTHOR + "/mnt/overlay/granite/ui/content/load.json"])
        self.assertEqual(result["sent_writes"], ["POST " + author_posts[0]])

    def test_adobe_sign_in_refresh_is_allowed(self):
        # Blocking this POST is what sent the real author's UI to Adobe sign-in.
        aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
        self.assertIn(("POST", IMS_TOKEN), self.seen)

    def test_several_captures_and_reruns_share_the_window(self):
        self.assertIs(aem_browser.get_window("env_test"), self.window)
        for _ in range(2):
            result = aem_browser.capture_page_properties(self.window, "/content/site/en", "tracking.example.com")
            self.assertEqual(len(result["fields"]), 1)

    def test_closed_window(self):
        aem_browser.close_window("env_test")
        self.assertIsNone(aem_browser.get_window("env_test"))
        with self.assertRaises(aem_browser.WindowClosed):
            self.window.capture([AUTHOR + "/mnt/x"], "x", timeout=5)


class WriteRuleTests(unittest.TestCase):
    def test_saves_to_author_are_blocked(self):
        from web_inspector.aem_screens import blocks_write
        saves = [
            ("POST", "/content/site/en/jcr:content"),           # Page Properties save
            ("POST", "/content/site/en/_jcr_content/root/text"),  # component dialog save
            ("POST", "/conf/site/settings/cloudconfigs"),
            ("POST", "/content.html"),
            ("POST", "/%63ontent/site/en"),                     # encoded
            ("POST", "/mnt/../content/site/en"),                # dot segments
            ("POST", "/bin/replicate.json"),
            ("POST", "/bin/wcmcommand"),
            ("POST", "/adobe/sites/pages"),
            ("delete", "/content/site/en"),
            ("PUT", "/mnt/overlay/x"),
        ]
        for method, path in saves:
            self.assertTrue(blocks_write(method, AUTHOR + path, AUTHOR), (method, path))

    def test_other_requests_are_allowed(self):
        from web_inspector.aem_screens import blocks_write
        self.assertFalse(blocks_write("GET", AUTHOR + "/content/site/en.html", AUTHOR))
        self.assertFalse(blocks_write("POST", AUTHOR + "/mnt/overlay/granite/ui/content/load.json", AUTHOR))
        self.assertFalse(blocks_write("POST", AUTHOR + "/content/cq:graphql/global/endpoint.json", AUTHOR))
        self.assertFalse(blocks_write("POST", AUTHOR + "/contentfinder", AUTHOR))
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


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowOptionTests(unittest.TestCase):
    def test_saving_allowed_when_blocking_is_off(self):
        seen = []
        window = aem_browser.open_window("env_open", AUTHOR, show_browser=False,
                                         prepare_context=strict_author(seen), timeout=20, block_saving=False)
        self.addCleanup(aem_browser.close_window, "env_open")
        result = aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")
        self.assertEqual(result["blocked_writes"], [])
        self.assertIn(("POST", AUTHOR + "/libs/granite/csrf/token.json"), seen)

    def test_remembered_sign_in_is_reused(self):
        import tempfile
        from pathlib import Path
        profile = Path(tempfile.mkdtemp()) / "env_saved"
        sent_cookie = []

        def prepare(context):
            def start(route):
                cookie = route.request.headers.get("cookie", "")
                sent_cookie.append("login-token=t" in cookie)
                # A lasting cookie, as Adobe's sign-in cookies are.
                route.fulfill(status=200, content_type="text/html",
                              headers={"Set-Cookie": "login-token=t; Path=/; Secure; Max-Age=3600"},
                              body="Start")
            context.route(AUTHOR + "/aem/start.html", start)

        for _ in range(2):
            window = aem_browser.open_window("env_saved", AUTHOR, show_browser=False, prepare_context=prepare,
                                             timeout=20, profile_dir=profile)
            aem_browser.close_window("env_saved")
            window.wait_closed()  # the profile is written as the browser closes
        self.assertEqual(sent_cookie, [False, True])  # the second window was already signed in

        aem_browser.forget_sign_in("env_saved", profile)
        self.assertFalse(profile.exists())


class NoticeTests(unittest.TestCase):
    def test_navigation_during_the_notice_does_not_fail_the_sign_in(self):
        from playwright.sync_api import Error as PlaywrightError

        class Page:  # as on the real author: AEM navigates again just after sign-in
            calls = 0

            def goto(self, *args, **kwargs):
                pass

            def set_content(self, *args, **kwargs):
                Page.calls += 1
                if Page.calls == 1:
                    raise PlaywrightError("Page.set_content: Execution context was destroyed, "
                                          "most likely because of a navigation")

            def is_closed(self):
                return False

            def wait_for_timeout(self, ms):
                pass

        aem_browser.AemWindow(AUTHOR)._show_notice(Page())  # doesn't raise
        self.assertEqual(Page.calls, 2)  # and tried again

    def test_notice_gives_up_quietly(self):
        from playwright.sync_api import Error as PlaywrightError

        class Page:
            def goto(self, *args, **kwargs):
                raise PlaywrightError("navigation interrupted")

            def is_closed(self):
                return False

            def wait_for_timeout(self, ms):
                pass

        aem_browser.AemWindow(AUTHOR)._show_notice(Page())  # doesn't raise


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowFailureTests(unittest.TestCase):
    def test_failing_aem_requests_are_listed(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/libs/granite/ui/broken.js*",
                          lambda route: route.fulfill(status=500, body="secret detail"))
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html",
                body="<script src='/libs/granite/ui/broken.js?x=1'></script>" + DIALOG))

        window = aem_browser.open_window("env_fail", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_fail")
        result = aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")
        self.assertIn("500 GET " + AUTHOR + "/libs/granite/ui/broken.js", result["failed_responses"])
        self.assertNotIn("secret", " ".join(result["failed_responses"]))

    def test_window_does_not_say_it_is_automated(self):
        page_html = ("<div class='coral-Form-fieldwrapper'><label>Automated</label><input name='./a'></div>"
                     "<script>document.querySelector('input').value = 'webdriver-' + navigator.webdriver</script>")

        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=page_html))

        window = aem_browser.open_window("env_plain", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_plain")
        result = window.capture([AUTHOR + "/mnt/x"], "webdriver-")
        self.assertEqual(result["fields"][0]["value"], "webdriver-false")


CORAL_LIKE = """<!doctype html><html><body>
<coral-tabview>
  <coral-tablist>
    <coral-tab id="t1" aria-controls="p1">Basic</coral-tab>
    <coral-tab id="t2" aria-controls="p2">Advanced</coral-tab>
    <coral-tab id="t3" aria-controls="p3">Custom</coral-tab>
  </coral-tablist>
  <coral-panelstack>
    <coral-panel id="p1">Basic fields</coral-panel>
    <coral-panel id="p2" style="display:none"><div class="coral-Form-fieldwrapper">
      <label>Analytics domain</label><input name="./analyticsDomain" value="tracking.example.com"></div></coral-panel>
    <coral-panel id="p3" style="display:none"><div class="coral-Form-fieldwrapper">
      <label>Tag host</label><input name="./tagHost" value="tags.example.com"></div></coral-panel>
  </coral-panelstack>
</coral-tabview>
<script>
  const show = id => document.querySelectorAll('coral-panel')
    .forEach(p => p.style.display = p.id === id ? '' : 'none');
  // Advanced: reacts to a real mouse press only, not to a script's click().
  document.getElementById('t2').addEventListener('mousedown', () => show('p2'));
  // Custom: ignores clicks; selectable only through Coral's "selected".
  Object.defineProperty(document.getElementById('t3'), 'selected', {set: v => v && show('p3')});
</script></body></html>"""


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowTabTests(unittest.TestCase):
    def setUp(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=CORAL_LIKE))

        self.window = aem_browser.open_window("env_tabs", AUTHOR, show_browser=False,
                                              prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_tabs")

    def test_tab_that_needs_a_real_click_is_opened(self):
        result = self.window.capture([AUTHOR + "/mnt/x"], "tracking.example.com")
        self.assertEqual(result["fields"][0]["tabs"], ["Advanced"])
        self.assertTrue(result["fields"][0]["visible"])

    def test_tab_that_ignores_clicks_is_selected_through_coral(self):
        result = self.window.capture([AUTHOR + "/mnt/x"], "tags.example.com")
        self.assertEqual(result["fields"][0]["tabs"], ["Custom"])
        self.assertTrue(result["fields"][0]["visible"])


DROPDOWN_IN_BASIC = CORAL_LIKE.replace(
    "<coral-panel id=\"p1\">Basic fields</coral-panel>",
    "<coral-panel id=\"p1\"><select name='./domain'><option value='other.example.com' selected>Other</option>"
    "<option value='tracking.example.com'>Tracking</option></select></coral-panel>")


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowChoiceTests(unittest.TestCase):
    def test_unchosen_dropdown_option_is_not_a_match(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=DROPDOWN_IN_BASIC))

        window = aem_browser.open_window("env_choice", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_choice")
        result = window.capture([AUTHOR + "/mnt/x"], "tracking.example.com")
        self.assertEqual([f["tabs"] for f in result["fields"]], [["Advanced"]])
        field = result["fields"][0]
        self.assertEqual(field["found_by"], ["aria-controls"])
        self.assertIn("coral-panel#p2", field["where"])


SCRIPT_FIELDS = CORAL_LIKE.replace(
    # Advanced: a code-editor field, its value in a hidden input.
    '<label>Analytics domain</label><input name="./analyticsDomain" value="tracking.example.com"></div>',
    '<label>Header scripts</label><input type="hidden" name="./headScripts" '
    'value="&lt;script src=&quot;https://tracking.example.com/a.js&quot;&gt;&lt;/script&gt;">'
    '<div class="editor">(code editor)</div></div>').replace(
    # Custom: the value only as text an editor shows.
    '<label>Tag host</label><input name="./tagHost" value="tags.example.com"></div>',
    '<label>Notes</label><div contenteditable>Loads from cdn.example.net</div></div>')


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowScriptFieldTests(unittest.TestCase):
    def setUp(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=SCRIPT_FIELDS))

        self.window = aem_browser.open_window("env_script", AUTHOR, show_browser=False,
                                              prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_script")

    def test_domain_in_a_hidden_script_value_opens_its_tab(self):
        result = self.window.capture([AUTHOR + "/mnt/x"], "tracking.example.com")
        field = result["fields"][0]
        self.assertEqual((field["tabs"], field["kind"], field["label"]), (["Advanced"], "hidden value", "Header scripts"))
        self.assertTrue(field["visible"])  # the field around the hidden input

    def test_domain_only_in_text_opens_its_tab(self):
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            result = self.window.capture([AUTHOR + "/mnt/x"], "cdn.example.net")
        field = result["fields"][0]
        self.assertEqual((field["tabs"], field["kind"]), (["Custom"], "text"))
        self.assertTrue(field["visible"])


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class DetachedChromeTests(unittest.TestCase):
    """With the sign-in remembered, Chrome outlives the app and is reused."""

    def test_window_survives_an_app_restart_in_the_same_tab(self):
        import tempfile
        from pathlib import Path
        profile = Path(tempfile.mkdtemp()) / "env_detached"
        self.addCleanup(aem_browser.forget_sign_in, "env_detached", profile)
        starts = []

        def prepare(context):
            strict_author([])(context)

            def start(route):
                starts.append(1)
                # Only the first sign-in puts AEM's sign-in in the tab's storage:
                # later screenshots work only in that same, still open tab.
                script = "sessionStorage.setItem('adobe-ims', 'signed-in')" if len(starts) == 1 else ""
                route.fulfill(status=200, content_type="text/html",
                              headers={"Set-Cookie": "login-token=t; Path=/; Secure; Max-Age=3600"},
                              body=f"<script>{script}</script>Start")
            context.route(AUTHOR + "/aem/start.html", start)

        def sign_in():
            return aem_browser.open_window("env_detached", AUTHOR, show_browser=False,
                                           prepare_context=prepare, timeout=20, profile_dir=profile)

        window = sign_in()
        self.assertTrue(window.detached)
        aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")

        # The app stops: its worker goes, Chrome stays.
        window.close(close_browser=False)
        window.wait_closed()
        aem_browser._windows.clear()
        self.assertTrue(aem_browser.detached_chrome_running(profile))

        # The next app run connects to it again and works in the same tab.
        window = sign_in()
        result = aem_browser.capture_page_properties(window, "/content/site/en", "tracking.example.com")
        self.assertEqual([f["label"] for f in result["fields"]], ["Analytics domain"])

        aem_browser.forget_sign_in("env_detached", profile)
        self.assertFalse(aem_browser.detached_chrome_running(profile))
        self.assertFalse(profile.exists())


ATTRIBUTE_ONLY = CORAL_LIKE.replace(
    '<label>Tag host</label><input name="./tagHost" value="tags.example.com"></div>',
    '<label>analyticsJS</label><div class="editor" data-value="&lt;script src=&quot;'
    'https://www.googletagmanager.com/gtm.js&quot;&gt;"></div></div>')


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class AemWindowNoMatchTests(unittest.TestCase):
    def open(self, body):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=body))

        window = aem_browser.open_window("env_nomatch", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_nomatch")
        return window

    def test_value_kept_in_an_attribute_opens_its_tab(self):
        result = self.open(ATTRIBUTE_ONLY).capture([AUTHOR + "/mnt/x"], "www.googletagmanager.com")
        field = result["fields"][0]
        self.assertEqual((field["tabs"], field["kind"]), (["Custom"], "attribute"))

    def test_no_match_says_what_the_dialog_has(self):
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            result = self.open(CORAL_LIKE).capture([AUTHOR + "/mnt/x"], "www.googletagmanager.com")
        self.assertEqual(result["fields"], [])
        self.assertEqual(result["no_match"]["tabs"], ["Basic", "Advanced", "Custom"])
        self.assertFalse(result["no_match"]["in_html"])


TEASER = CORAL_LIKE.replace(
    # Advanced: rich text, its value as HTML in a hidden input.
    '<label>Analytics domain</label><input name="./analyticsDomain" value="tracking.example.com"></div>',
    '<label>Description</label><input type="hidden" name="./jcr:description" '
    'value="&lt;p&gt;Featured&amp;nbsp;&lt;b&gt;stories&lt;/b&gt;&lt;/p&gt;"><div class="rte">Featured stories</div></div>'
).replace(
    # Custom: the words in another order.
    '<label>Tag host</label><input name="./tagHost" value="tags.example.com"></div>',
    '<label>Title</label><input name="./jcr:title" value="Stories we featured"></div>')


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class LooseMatchTests(unittest.TestCase):
    def setUp(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=TEASER))

        self.window = aem_browser.open_window("env_loose", AUTHOR, show_browser=False,
                                              prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_loose")

    def test_term_with_punctuation_matches_rich_text(self):
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            result = self.window.capture([AUTHOR + "/mnt/x"], "Featured stories..")
        [field] = result["fields"]
        self.assertEqual((field["label"], field["tabs"], field["matched"]), ("Description", ["Advanced"], "cleaned"))
        self.assertTrue(field["visible"])

    def test_words_in_another_order_match_last(self):
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            result = self.window.capture([AUTHOR + "/mnt/x"], "featured we stories")
        [field] = result["fields"]
        self.assertEqual((field["tabs"], field["matched"]), (["Custom"], "words"))

    def test_exact_text_still_comes_first(self):
        result = self.window.capture([AUTHOR + "/mnt/x"], "Stories we featured")
        self.assertEqual([f["matched"] for f in result["fields"]], ["exact"])


IMAGE_ONLY = CORAL_LIKE.replace(
    '<label>Analytics domain</label><input name="./analyticsDomain" value="tracking.example.com"></div>',
    '<label>Image asset</label><input name="./fileReference" value="/content/dam/site/featured-stories.jpg"></div>')


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class PathWordsTests(unittest.TestCase):
    def test_words_of_an_image_file_name_are_not_a_match(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=IMAGE_ONLY))

        window = aem_browser.open_window("env_image", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_image")
        with mock.patch.object(aem_screens, "FIELD_WAIT_SECONDS", 0):
            result = window.capture([AUTHOR + "/mnt/x"], "Featured stories..")
        self.assertEqual(result["fields"], [])


TWICE = CORAL_LIKE.replace(
    # The value on the input and on an element around it, in one form field.
    '<label>Analytics domain</label><input name="./analyticsDomain" value="tracking.example.com"></div>',
    '<label>Title</label><coral-textfield value="tracking.example.com">'
    '<input name="./jcr:title" value="tracking.example.com"></coral-textfield></div>')


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class OncePerFieldTests(unittest.TestCase):
    def test_one_screenshot_per_field_with_a_banner(self):
        def prepare(context):
            strict_author([])(context)
            context.route(AUTHOR + "/mnt/**", lambda route: route.fulfill(
                status=200, content_type="text/html", body=TWICE))

        window = aem_browser.open_window("env_twice", AUTHOR, show_browser=False,
                                         prepare_context=prepare, timeout=20)
        self.addCleanup(aem_browser.close_window, "env_twice")
        result = window.capture([AUTHOR + "/mnt/x"], "tracking.example.com", label="Title component")
        [field] = result["fields"]
        self.assertEqual(field["tabs"], ["Advanced"])
        self.assertTrue(field["image"].startswith(b"\x89PNG"))
