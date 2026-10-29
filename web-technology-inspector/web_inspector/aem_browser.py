"""A signed-in AEM author window that stays open for the session.

AEM's UI checks the Adobe sign-in inside the browser itself, in storage that
can't be copied to another browser, so screenshots must be taken in the same
window, and the same tab, the user signed in with.

Playwright objects belong to the thread that created them, and Streamlit runs
each rerun on a new thread, so one worker thread per window owns Playwright
and runs commands sent to it through a queue.

Read-only: once signed in, every request from the window to author that isn't
a read is blocked, including anything done by hand in it (see
aem_screens.blocks_write). Closing the window ends the session.
"""

from __future__ import annotations

import queue
import threading

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .aem_screens import (
    SignInIncomplete,
    _capture_in_page,
    blocks_write,
    _signed_in,
    component_dialog_urls,
    properties_url,
)

_windows: dict[str, "AemWindow"] = {}
_lock = threading.Lock()


class WindowClosed(RuntimeError):
    """The AEM window was closed, or its worker stopped."""


class AemWindow:
    def __init__(self, author_base: str, *, show_browser: bool = True, prepare_context=None):
        self.author_base = author_base
        self._show_browser = show_browser
        self._prepare_context = prepare_context
        self._commands: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._error: BaseException | None = None
        self.storage_state: dict | None = None
        self.blocked: list[str] = []
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

    # --- worker thread ---------------------------------------------------------

    def _guard(self, context) -> None:
        def handle(route):
            if blocks_write(route.request.method, route.request.url, self.author_base):
                self.blocked.append(f"{route.request.method} {route.request.url}")
                route.abort()
            else:
                route.fallback()
        context.route("**/*", handle)

    def _run(self) -> None:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not self._show_browser)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 1000})
                    if self._prepare_context:
                        self._prepare_context(context)
                    page = context.new_page()
                    page.goto(self.author_base.rstrip("/") + "/aem/start.html",
                              wait_until="domcontentloaded", timeout=60_000)
                    for _ in range(self._sign_in_timeout):
                        if page.is_closed():
                            raise SignInIncomplete("The AEM window was closed before signing in")
                        if _signed_in(page, context, self.author_base):
                            break
                        page.wait_for_timeout(1000)
                    else:
                        raise SignInIncomplete(f"Not signed in within {self._sign_in_timeout // 60} minutes")

                    # Signing in is done: from now on the window may only read.
                    self._guard(context)
                    self.storage_state = context.storage_state()
                    self._ready.set()
                    self._serve(page)
                finally:
                    browser.close()
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
                before = len(self.blocked)
                result = _capture_in_page(page, self.author_base, urls, term, self.blocked, timeout)
                result["blocked_writes"] = self.blocked[before:]
                box["result"] = result
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting caller
                box["error"] = exc
            finally:
                done.set()


# --- registry: one window per AEM environment, shared across reruns ---------------

def open_window(environment_id: str, author_base: str, *, show_browser: bool = True,
                prepare_context=None, timeout: int = 300) -> AemWindow:
    """Open (or replace) the environment's window and wait for the sign-in."""
    with _lock:
        old = _windows.pop(environment_id, None)
    if old:
        old.close()
    window = AemWindow(author_base, show_browser=show_browser, prepare_context=prepare_context)
    window.start(timeout)
    with _lock:
        _windows[environment_id] = window
    return window


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
