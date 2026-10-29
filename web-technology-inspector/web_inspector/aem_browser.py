"""A signed-in AEM author window that stays open for the session.

AEM's UI checks the Adobe sign-in inside the browser itself, in storage that
can't be copied to another browser, so screenshots must be taken in the same
window, and the same tab, the user signed in with.

Playwright objects belong to the thread that created them, and Streamlit runs
each rerun on a new thread, so one worker thread per window owns Playwright
and runs commands sent to it through a queue.

Optionally no saving: once signed in, every request from the window that
would change content in author is blocked, including anything done by hand
in it (see aem_screens.blocks_write). Off, the window is like the user's own
browser: the tool itself still only opens pages and clicks dialog tabs.

The sign-in can be remembered: the window then keeps its own browser profile
(cookies and storage, in the git-ignored data folder), so the next sign-in
goes through by itself while AEM and Adobe still accept the saved login.
Chrome then also runs as its own program (chrome_process), so stopping the
app leaves it open and signed in, and the next start connects to the same
tab again. Otherwise closing the window ends the session.
"""

from __future__ import annotations

import queue
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .aem_screens import (
    READ_METHODS,
    AemLoginRequired,
    DialogNotOpened,
    SignInIncomplete,
    _capture_in_editor,
    _capture_in_page,
    blocks_write,
    _signed_in,
    properties_url,
)
from . import chrome_process
from .logging_setup import get_logger
from .utils import harden_file_permissions

log = get_logger()

SIGNED_IN_NOTICE = """<!doctype html><title>AEM - signed in</title>
<body style="font: 16px system-ui, sans-serif; margin: 3rem; max-width: 40rem; color: #222">
<h2>Signed in to AEM</h2>
<p>Web Technology Inspector takes its AEM screenshots in this window. Keep it open;
closing it signs out.</p>
<p>Nothing can be saved to AEM from this window: saving, publishing, deleting
and workflows are blocked, so AEM shows an error if you try.</p></body>"""

STAYS_OPEN = ("<p>It stays open when the app stops, and the app connects to it again on its next "
              "start, so you stay signed in.</p>")

SIGNED_IN_NOTICE_OPEN = """<!doctype html><title>AEM - signed in</title>
<body style="font: 16px system-ui, sans-serif; margin: 3rem; max-width: 40rem; color: #222">
<h2>Signed in to AEM</h2>
<p>Web Technology Inspector takes its AEM screenshots in this window. Keep it open;
closing it signs out.</p>
<p>Saving isn't blocked in this window (it's off in the app): it works like your
own browser, so take care with anything you do here by hand.</p></body>"""

_windows: dict[str, "AemWindow"] = {}
_lock = threading.Lock()


def _close_chrome(browser) -> None:
    try:
        browser.new_browser_cdp_session().send("Browser.close")
    except PlaywrightError:
        pass  # already closed


class WindowClosed(RuntimeError):
    """The AEM window was closed, or its worker stopped."""


class AemWindow:
    def __init__(self, author_base: str, *, show_browser: bool = True, prepare_context=None,
                 block_saving: bool = True, profile_dir: Path | None = None, use_chrome: bool = False):
        self.author_base = author_base
        self._show_browser = show_browser
        self._prepare_context = prepare_context
        self._block_saving = block_saving
        self._profile_dir = profile_dir
        self._use_chrome = use_chrome
        # With a saved profile, Chrome runs as its own program and outlives
        # the app; it's only closed on purpose (sign out, forget the sign-in).
        self.detached = profile_dir is not None
        self._close_browser = False
        self._commands: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._error: BaseException | None = None
        self.storage_state: dict | None = None
        self.blocked: list[str] = []
        self.sent: list[str] = []  # POSTs to author let through: not saves
        self.failures: list[str] = []  # AEM and Adobe answers that failed, address and status only
        self._thread = threading.Thread(target=self._run, name="aem-window", daemon=True)

    # --- called from Streamlit threads ---------------------------------------

    def start(self, timeout: int = 300) -> None:
        """Open the window and wait until the user has signed in."""
        self._sign_in_timeout = timeout
        self._thread.start()
        self._ready.wait(timeout + 90)
        if self._error:
            raise self._error
        if not self._ready.is_set():
            raise SignInIncomplete(f"Not signed in within {timeout // 60} minutes")

    @property
    def alive(self) -> bool:
        return (self._thread.is_alive() and self._ready.is_set() and self._error is None
                and not self._closed.is_set())

    def capture(self, urls: list[str], term: str, timeout: int = 60, *, component: str | None = None,
                label: str = "") -> dict:
        """Screenshot the fields containing term: in the first of urls that
        renders (Page Properties), or, with component (a node path), in that
        component's dialog opened in the page editor."""
        if not self.alive:
            raise WindowClosed("The AEM window is closed")
        done = threading.Event()
        box: dict = {}
        self._commands.put(("capture", (urls, term, timeout, component, label), box, done))
        # Wait in short steps, so a window closed meanwhile fails at once.
        for _ in range(timeout + 60):
            if done.wait(1) or not self._thread.is_alive():
                break
        if "error" not in box and "result" not in box:
            raise WindowClosed("The AEM window was closed or didn't respond")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def close(self, *, close_browser: bool = True) -> None:
        """Stop the window; close_browser=False leaves a detached Chrome open."""
        self._close_browser = close_browser
        self._closed.set()
        if self._thread.is_alive():
            self._commands.put(("close", None, {}, threading.Event()))

    def wait_closed(self, timeout: int = 15) -> None:
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    # --- worker thread ---------------------------------------------------------

    def _guard(self, context) -> None:
        def handle(route):
            if blocks_write(route.request.method, route.request.url, self.author_base):
                self.blocked.append(f"{route.request.method} {route.request.url}")
                route.abort()
            else:
                if route.request.method.upper() not in READ_METHODS and \
                        route.request.url.lower().startswith(self.author_base.lower().rstrip("/") + "/"):
                    self.sent.append(f"{route.request.method} {route.request.url.split('?')[0]}")
                route.fallback()
        context.route("**/*", handle)

    def _attach(self, playwright):
        """(browser, context) of the profile's own Chrome: the one already
        running (from an earlier app run), else a newly started one."""
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        harden_file_permissions(self._profile_dir, mode=0o700)
        port = chrome_process.running_port(self._profile_dir)
        log.info("AEM window: %s", f"reconnecting to its Chrome on port {port}" if port else "starting its Chrome")
        if not port:
            installed = self._use_chrome and chrome_process.installed_chrome()
            port = chrome_process.launch(installed or playwright.chromium.executable_path,
                                         self._profile_dir, "about:blank",
                                         headless=not self._show_browser, sandbox=bool(installed))
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        return browser, browser.contexts[0]

    def _tab(self, context):
        """The tab to use: in a reused Chrome the one signed in before (AEM's
        sign-in lives in that tab), else the first or a new one."""
        author = self.author_base.lower().rstrip("/")
        for page in context.pages:
            try:
                if page.url.lower().startswith(author) or page.title() == "AEM - signed in":
                    return page
            except PlaywrightError:
                continue
        return context.pages[0] if context.pages else context.new_page()

    def _open(self, playwright):
        """(browser or None, context): the installed Chrome if wanted and there,
        else Playwright's Chromium; with the saved profile if remembering."""
        if self.detached:
            return self._attach(playwright)
        # Without Playwright's "automated browser" switches, so the window is
        # a plain Chrome to AEM and Adobe, like the user's own browser.
        options = {"headless": not self._show_browser, "ignore_default_args": ["--enable-automation"],
                   "args": ["--disable-blink-features=AutomationControlled"]}
        channels = ["chrome", None] if self._use_chrome else [None]
        for channel in channels:
            launch = dict(options, **({"channel": channel} if channel else {}))
            try:
                if self._profile_dir:
                    self._profile_dir.mkdir(parents=True, exist_ok=True)
                    harden_file_permissions(self._profile_dir, mode=0o700)
                    context = playwright.chromium.launch_persistent_context(
                        str(self._profile_dir), viewport={"width": 1440, "height": 1000}, **launch)
                    return None, context
                browser = playwright.chromium.launch(**launch)
                return browser, browser.new_context(viewport={"width": 1440, "height": 1000})
            except PlaywrightError:
                if channel is None:
                    raise  # Chrome isn't installed: Chromium was the fallback

    def _watch_failures(self, context) -> None:
        """Note failing answers from author and Adobe (no bodies or headers):
        they say why AEM's UI shows an error page."""
        author = self.author_base.lower().rstrip("/")

        def relevant(url: str) -> bool:
            host = (urlsplit(url).hostname or "").lower()
            return url.lower().startswith(author + "/") or host.endswith((".adobe.com", ".adobelogin.com"))

        def response(response):
            if response.status >= 400 and relevant(response.url):
                self.failures.append(f"{response.status} {response.request.method} {response.url.split('?')[0]}")

        def failed(request):
            if relevant(request.url) and request.failure != "net::ERR_ABORTED" \
                    and f"{request.method} {request.url}" not in self.blocked:  # listed as blocked
                self.failures.append(f"{request.failure} {request.method} {request.url.split('?')[0]}")

        context.on("response", response)
        context.on("requestfailed", failed)

    def _show_notice(self, page) -> None:
        """The start page isn't needed: say what the window is for instead.

        Same tab, so the sign-in stays. AEM may still be navigating (a
        redirect after sign-in), which interrupts this; the notice is only a
        nicety, so that never fails the sign-in."""
        notice = SIGNED_IN_NOTICE if self._block_saving else SIGNED_IN_NOTICE_OPEN
        if self.detached:
            notice = notice.replace("<p>Web Technology Inspector takes its AEM screenshots in this window. Keep it open;\n"
                                    "closing it signs out.</p>",
                                    "<p>Web Technology Inspector takes its AEM screenshots in this window.</p>" + STAYS_OPEN)
        for _ in range(3):
            try:
                page.goto("about:blank", wait_until="load", timeout=10_000)  # stops AEM's navigation
                page.set_content(notice, timeout=10_000)
                return
            except PlaywrightError:
                if page.is_closed():
                    return
                page.wait_for_timeout(1000)

    def _run(self) -> None:
        try:
            with sync_playwright() as playwright:
                browser, context = self._open(playwright)
                try:
                    if self._prepare_context:
                        self._prepare_context(context)
                    self._watch_failures(context)
                    page = self._tab(context)
                    page.goto(self.author_base.rstrip("/") + "/aem/start.html",
                              wait_until="domcontentloaded", timeout=60_000)
                    if self._profile_dir:
                        # A saved login AEM no longer accepts redirects to sign-in in script.
                        page.wait_for_timeout(2000)
                    for _ in range(self._sign_in_timeout):
                        if page.is_closed():
                            raise SignInIncomplete("The AEM window was closed before signing in")
                        if _signed_in(page, context, self.author_base):
                            break
                        page.wait_for_timeout(1000)
                    else:
                        raise SignInIncomplete(f"Not signed in within {self._sign_in_timeout // 60} minutes")

                    if self._block_saving:
                        # Signing in is done: from now on the window can't save.
                        self._guard(context)
                    self.storage_state = context.storage_state()
                    self._show_notice(page)
                    log.info("AEM window signed in to %s (saving %s)", self.author_base,
                             "blocked" if self._block_saving else "not blocked")
                    self._ready.set()
                    self._serve(page)
                finally:
                    if not self.detached:
                        (browser or context).close()
                    elif self._close_browser:
                        _close_chrome(browser)
                    # else: leave the detached Chrome open; the app only disconnects
        except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
            if not isinstance(exc, (WindowClosed, SignInIncomplete)):
                log.exception("AEM window stopped")
            else:
                log.info("AEM window ended: %s", exc)
            self._error = exc
            self._ready.set()
        finally:
            self._closed.set()

    def _serve(self, page) -> None:
        while True:
            try:
                command, args, box, done = self._commands.get_nowait()
            except queue.Empty:
                if page.is_closed():
                    raise WindowClosed("The AEM window was closed")
                # Wait inside Playwright, not on the queue: the read-only guard
                # answers the page's requests only while Playwright runs here,
                # so blocking on the queue left AEM's UI hanging between captures.
                try:
                    page.wait_for_timeout(200)
                except PlaywrightError as exc:
                    raise WindowClosed("The AEM window was closed") from exc
                continue
            if command == "close":
                done.set()
                return
            try:
                if page.is_closed():
                    raise WindowClosed("The AEM window was closed")
                urls, term, timeout, component, label = args
                before, sent_before, failed_before = len(self.blocked), len(self.sent), len(self.failures)
                log.info("AEM screenshot: %s, term %r", f"component {component}" if component else urls[0], term)
                if component:
                    result = _capture_in_editor(page, self.author_base, component, term, self.blocked, timeout,
                                                label)
                else:
                    result = _capture_in_page(page, self.author_base, urls, term, self.blocked, timeout, label)
                _log_result(result, self.failures[failed_before:])
                result["blocked_writes"] = self.blocked[before:]
                result["sent_writes"] = self.sent[sent_before:]
                result["failed_responses"] = self.failures[failed_before:]
                box["result"] = result
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
                log.error("AEM screenshot failed: %s: %s%s", type(exc).__name__, exc,
                          f" | step: {exc.step} | editor: {exc.state}" if isinstance(exc, DialogNotOpened) else "",
                          exc_info=not isinstance(exc, (DialogNotOpened, AemLoginRequired)))
                failed = self.failures[failed_before:]
                if failed:
                    log.error("AEM requests that failed meanwhile: %s", failed[:20])
                box["error"] = exc
            finally:
                done.set()


def _log_result(result: dict, failed: list[str]) -> None:
    """One line per screenshot outcome: addresses, statuses, tabs; no values."""
    attempts = ", ".join(f"{a['url'].split('?')[0]} -> {a['status']}" for a in result.get("attempts", []))
    if result["fields"]:
        log.info("AEM screenshot taken: %s | fields: %s", attempts,
                 [(f["label"] or f["name"], " > ".join(f["tabs"]), f["kind"], f["matched"], f["visible"])
                  for f in result["fields"]])
    else:
        log.warning("AEM screenshot found no match: %s | dialog: %s", attempts, result.get("no_match"))
    if failed:
        log.warning("AEM requests that failed meanwhile: %s", failed[:20])


# --- registry: one window per AEM environment, shared across reruns ---------------

def open_window(environment_id: str, author_base: str, *, show_browser: bool = True,
                prepare_context=None, timeout: int = 300, block_saving: bool = True,
                profile_dir: Path | None = None, use_chrome: bool = False) -> AemWindow:
    """Open (or replace) the environment's window and wait for the sign-in."""
    with _lock:
        old = _windows.pop(environment_id, None)
    if old:
        old.close(close_browser=False)  # a detached Chrome is reused by the new window
        old.wait_closed()
    window = AemWindow(author_base, show_browser=show_browser, prepare_context=prepare_context,
                       block_saving=block_saving, profile_dir=profile_dir, use_chrome=use_chrome)
    window.start(timeout)
    with _lock:
        _windows[environment_id] = window
    return window


def forget_sign_in(environment_id: str, profile_dir: Path) -> None:
    """Close the environment's window and Chrome, and delete its saved profile."""
    with _lock:
        window = _windows.pop(environment_id, None)
    if window:
        window.close()
        window.wait_closed()
    close_detached_chrome(profile_dir)
    shutil.rmtree(profile_dir, ignore_errors=True)


def close_detached_chrome(profile_dir: Path, timeout: int = 15) -> None:
    """Close a Chrome left running with the profile (e.g. by an earlier app run)."""
    port = chrome_process.running_port(profile_dir)
    if not port:
        return
    with sync_playwright() as playwright:
        try:
            _close_chrome(playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}"))
        except PlaywrightError:
            pass
    for _ in range(timeout * 2):  # its files stay in use until it has exited
        if not chrome_process.running_port(profile_dir):
            return
        time.sleep(0.5)


def detached_chrome_running(profile_dir: Path) -> bool:
    return chrome_process.running_port(profile_dir) is not None


def get_window(environment_id: str) -> AemWindow | None:
    with _lock:
        window = _windows.get(environment_id)
    return window if window and window.alive else None


def open_windows() -> dict[str, AemWindow]:
    """Every window still open and signed in, by environment id."""
    with _lock:
        return {key: window for key, window in _windows.items() if window.alive}


def close_window(environment_id: str) -> None:
    with _lock:
        window = _windows.pop(environment_id, None)
    if window:
        window.close()


def capture_page_properties(window: AemWindow, page_path: str, term: str, label: str = "Page Properties") -> dict:
    return window.capture([properties_url(window.author_base, page_path)], term, label=label)


def capture_component_dialog(window: AemWindow, node_path: str, term: str, label: str = "") -> dict:
    """The component's dialog, opened in the page editor as an author would."""
    return window.capture([], term, timeout=90, component=node_path, label=label)
