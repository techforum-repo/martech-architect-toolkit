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
Otherwise closing the window ends the session.
"""

from __future__ import annotations

import queue
import shutil
import threading
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .aem_screens import (
    READ_METHODS,
    SignInIncomplete,
    _capture_in_page,
    blocks_write,
    _signed_in,
    component_dialog_urls,
    properties_url,
)
from .utils import harden_file_permissions

SIGNED_IN_NOTICE = """<!doctype html><title>AEM - signed in</title>
<body style="font: 16px system-ui, sans-serif; margin: 3rem; max-width: 40rem; color: #222">
<h2>Signed in to AEM</h2>
<p>Web Technology Inspector takes its AEM screenshots in this window. Keep it open;
closing it signs out.</p>
<p>Nothing can be saved to AEM from this window: saving, publishing, deleting
and workflows are blocked, so AEM shows an error if you try.</p></body>"""

SIGNED_IN_NOTICE_OPEN = """<!doctype html><title>AEM - signed in</title>
<body style="font: 16px system-ui, sans-serif; margin: 3rem; max-width: 40rem; color: #222">
<h2>Signed in to AEM</h2>
<p>Web Technology Inspector takes its AEM screenshots in this window. Keep it open;
closing it signs out.</p>
<p>Saving isn't blocked in this window (it's off in the app): it works like your
own browser, so take care with anything you do here by hand.</p></body>"""

_windows: dict[str, "AemWindow"] = {}
_lock = threading.Lock()


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
        self._commands: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._error: BaseException | None = None
        self.storage_state: dict | None = None
        self.blocked: list[str] = []
        self.sent: list[str] = []  # POSTs to author let through: not saves
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

    def capture(self, urls: list[str], term: str, timeout: int = 60) -> dict:
        if not self.alive:
            raise WindowClosed("The AEM window is closed")
        done = threading.Event()
        box: dict = {}
        self._commands.put(("capture", (urls, term, timeout), box, done))
        # Wait in short steps, so a window closed meanwhile fails at once.
        for _ in range(timeout + 60):
            if done.wait(1) or not self._thread.is_alive():
                break
        if "error" not in box and "result" not in box:
            raise WindowClosed("The AEM window was closed or didn't respond")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def close(self) -> None:
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

    def _open(self, playwright):
        """(browser or None, context): the installed Chrome if wanted and there,
        else Playwright's Chromium; with the saved profile if remembering."""
        options = {"headless": not self._show_browser}
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

    def _run(self) -> None:
        try:
            with sync_playwright() as playwright:
                browser, context = self._open(playwright)
                try:
                    if self._prepare_context:
                        self._prepare_context(context)
                    page = context.pages[0] if context.pages else context.new_page()
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
                    # The start page isn't needed: say what the window is for
                    # instead. Same tab, so the sign-in stays.
                    page.set_content(SIGNED_IN_NOTICE if self._block_saving else SIGNED_IN_NOTICE_OPEN)
                    self._ready.set()
                    self._serve(page)
                finally:
                    (browser or context).close()
        except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
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
                urls, term, timeout = args
                before, sent_before = len(self.blocked), len(self.sent)
                result = _capture_in_page(page, self.author_base, urls, term, self.blocked, timeout)
                result["blocked_writes"] = self.blocked[before:]
                result["sent_writes"] = self.sent[sent_before:]
                box["result"] = result
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
                box["error"] = exc
            finally:
                done.set()


# --- registry: one window per AEM environment, shared across reruns ---------------

def open_window(environment_id: str, author_base: str, *, show_browser: bool = True,
                prepare_context=None, timeout: int = 300, block_saving: bool = True,
                profile_dir: Path | None = None, use_chrome: bool = False) -> AemWindow:
    """Open (or replace) the environment's window and wait for the sign-in."""
    with _lock:
        old = _windows.pop(environment_id, None)
    if old:
        old.close()
        old.wait_closed()  # a saved profile can only be open in one window
    window = AemWindow(author_base, show_browser=show_browser, prepare_context=prepare_context,
                       block_saving=block_saving, profile_dir=profile_dir, use_chrome=use_chrome)
    window.start(timeout)
    with _lock:
        _windows[environment_id] = window
    return window


def forget_sign_in(environment_id: str, profile_dir: Path) -> None:
    """Close the environment's window and delete its saved browser profile."""
    with _lock:
        window = _windows.pop(environment_id, None)
    if window:
        window.close()
        window.wait_closed()
    shutil.rmtree(profile_dir, ignore_errors=True)


def get_window(environment_id: str) -> AemWindow | None:
    with _lock:
        window = _windows.get(environment_id)
    return window if window and window.alive else None


def close_window(environment_id: str) -> None:
    with _lock:
        window = _windows.pop(environment_id, None)
    if window:
        window.close()


def capture_page_properties(window: AemWindow, page_path: str, term: str) -> dict:
    return window.capture([properties_url(window.author_base, page_path)], term)


def capture_component_dialog(window: AemWindow, node_path: str, resource_type: str, term: str) -> dict:
    return window.capture(component_dialog_urls(window.author_base, node_path, resource_type), term)
