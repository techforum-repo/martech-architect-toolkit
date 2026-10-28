"""Playwright browser scan with Chrome DevTools Protocol request evidence.

One scan loads the page, scrolls it so lazy tags fire, and records every
request with its initiator, redirect hops, size and timing, plus cookies,
known page globals and a screenshot, all from the same browser session.

With consent="accept" the scan clicks the consent banner's accept button
after the page has settled, so requests and cookies are split into
before-consent and after-consent: anything recorded before the click fired
without consent.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .detection import GLOBAL_NAMES

# Accept buttons of common consent platforms, tried in order.
CONSENT_BUTTONS = {
    "OneTrust": "#onetrust-accept-btn-handler",
    "Cookiebot": "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "TrustArc": "#truste-consent-button",
    "Didomi": "#didomi-notice-agree-button",
    "Usercentrics": "button[data-testid='uc-accept-all-button']",
    "Quantcast": ".qc-cmp2-summary-buttons button[mode='primary']",
    # Sourcepoint renders inside its own iframe; choice type 11 is "Accept all".
    "Sourcepoint": "button.sp_choice_type_11",
}

# Page titles that bot-protection services show instead of the page.
BLOCK_PAGE_TITLE = re.compile(
    r"access denied|attention required|just a moment|request rejected|forbidden",
    re.IGNORECASE,
)

MAX_INLINE_SCRIPTS = 200
MAX_INLINE_SCRIPT_CHARS = 200_000

DESKTOP = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
MOBILE_DEVICE = "Pixel 7"

# Scroll down in steps so lazy-loaded content and scroll-triggered tags fire.
SCROLL_SCRIPT = """async () => {
    const step = Math.max(window.innerHeight * 0.8, 400);
    for (let y = 0; y < document.body.scrollHeight && y < 30000; y += step) {
        window.scrollTo(0, y);
        await new Promise(resolve => setTimeout(resolve, 250));
    }
    window.scrollTo(0, 0);
}"""

GLOBALS_SCRIPT = """names => names.filter(name => {
    try {
        return name.split('.').reduce((o, k) => (o == null ? undefined : o[k]), window) !== undefined;
    } catch (e) { return false; }
})"""


class ScanBlocked(RuntimeError):
    """The website answered with a bot-protection or access-denied page."""


def _desktop_user_agent(browser_version: str) -> str:
    # Headless Chromium announces "HeadlessChrome", which many sites block
    # outright; present as the same Chrome version on Windows instead.
    major = browser_version.split(".")[0]
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def _settle(page, seconds: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=seconds * 1000)
    except PlaywrightTimeout:
        pass  # Pages with polling or streaming never go idle; carry on.


def _cookies(context) -> list[dict]:
    """Cookie metadata only; values are never stored."""
    return [
        {
            "name": c["name"],
            "domain": c["domain"].lstrip("."),
            "path": c["path"],
            "session": c.get("expires", -1) in (-1, 0),
            "expires": c.get("expires", -1),
            "http_only": c["httpOnly"],
            "secure": c["secure"],
            "same_site": c.get("sameSite", ""),
        }
        for c in context.cookies()
    ]


def _accept_consent(page) -> str | None:
    """Click the first consent accept button found; return the platform name."""
    for frame in page.frames:
        for platform, selector in CONSENT_BUTTONS.items():
            try:
                button = frame.locator(selector).first
                if button.count() and button.is_visible():
                    button.click(timeout=3000)
                    return platform
            except PlaywrightError:
                continue
    return None


def scan(url: str, *, device: str = "desktop", consent: str = "none",
         show_browser: bool = False, timeout: int = 45, settle: int = 6,
         prepare_context=None) -> dict:
    """Load the page in Chromium and return the observed evidence.

    device: "desktop" or "mobile". consent: "none" (never touch the banner)
    or "accept" (accept it after the first settle and split the evidence).
    prepare_context: optional callable given the browser context before the
    page opens; the tests use it to serve fixture pages without a network.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("A valid HTTPS URL is required")

    entries: list[dict] = []
    current: dict[str, int] = {}  # CDP requestId -> index of its latest hop
    started: dict[str, float] = {}
    state = {"phase": "before_consent" if consent == "accept" else "page_load"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not show_browser)
        try:
            if device == "mobile":
                options = dict(playwright.devices[MOBILE_DEVICE])
            else:
                options = dict(DESKTOP, user_agent=_desktop_user_agent(browser.version))
            context = browser.new_context(service_workers="block", accept_downloads=False, **options)
            if prepare_context:
                prepare_context(context)
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")

            def on_request(event):
                request_id = event["requestId"]
                request = event.get("request", {})
                initiator = event.get("initiator", {})
                frames = (initiator.get("stack") or {}).get("callFrames") or []
                frame_urls = [f["url"] for f in frames if f.get("url")]

                # CDP reuses the requestId for each redirect hop; close the
                # previous hop with its redirect status instead of overwriting it.
                redirect = event.get("redirectResponse")
                previous = current.get(request_id)
                if redirect and previous is not None:
                    entries[previous]["status"] = redirect.get("status")
                    entries[previous]["redirected_to"] = request.get("url", "")

                request_url = request.get("url", "")
                entries.append({
                    "url": request_url,
                    "domain": urlparse(request_url).hostname or "",
                    "method": request.get("method", ""),
                    "type": event.get("type", ""),
                    "initiator_type": initiator.get("type", ""),
                    "initiator_url": initiator.get("url") or (frame_urls[0] if frame_urls else ""),
                    "stack_urls": frame_urls,
                    "redirect_from": entries[previous]["url"] if redirect and previous is not None else "",
                    "redirected_to": "",
                    "status": None,
                    "mime_type": "",
                    "bytes": 0,
                    "duration_ms": None,
                    "failed": "",
                    "phase": state["phase"],
                })
                current[request_id] = len(entries) - 1
                started[request_id] = event.get("timestamp", 0.0)

            def entry_for(event):
                index = current.get(event.get("requestId"))
                return entries[index] if index is not None else None

            def on_response(event):
                entry = entry_for(event)
                if entry is not None:
                    response = event.get("response", {})
                    entry["status"] = response.get("status")
                    entry["mime_type"] = response.get("mimeType", "")

            def on_finished(event):
                entry = entry_for(event)
                if entry is not None:
                    entry["bytes"] = int(event.get("encodedDataLength") or 0)
                    begin = started.get(event["requestId"])
                    if begin:
                        entry["duration_ms"] = round((event.get("timestamp", begin) - begin) * 1000)

            def on_failed(event):
                entry = entry_for(event)
                if entry is not None:
                    entry["failed"] = event.get("errorText", "failed")

            cdp.on("Network.requestWillBeSent", on_request)
            cdp.on("Network.responseReceived", on_response)
            cdp.on("Network.loadingFinished", on_finished)
            cdp.on("Network.loadingFailed", on_failed)

            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            main_status = response.status if response else None
            title = page.title()

            if (main_status in (401, 403, 429)) or (
                BLOCK_PAGE_TITLE.search(title or "") and len(entries) <= 5
            ):
                raise ScanBlocked(
                    f"The website answered with '{title or 'no title'}' (HTTP {main_status})"
                )

            _settle(page, settle)
            page.evaluate(SCROLL_SCRIPT)
            _settle(page, settle)

            consent_result = {"mode": consent, "platform": None, "accepted": False}
            cookies_before = None
            if consent == "accept":
                cookies_before = _cookies(context)
                # Switch the label before clicking: the click itself starts
                # the requests consent unlocks.
                state["phase"] = "after_consent"
                platform = _accept_consent(page)
                consent_result.update(platform=platform, accepted=bool(platform))
                if platform:
                    _settle(page, settle)
                else:
                    state["phase"] = "before_consent"  # nothing was accepted

            def evaluate_all(selector, script):
                return page.locator(selector).evaluate_all(script)

            inline = evaluate_all("script:not([src])", "els => els.map(e => e.textContent || '')")

            return {
                "url": url,
                "final_url": page.url,
                "title": page.title(),
                "main_status": main_status,
                "device": device,
                "user_agent": page.evaluate("navigator.userAgent"),
                "consent": consent_result,
                "requests": entries,
                "scripts": evaluate_all("script[src]", "els => els.map(e => e.src)"),
                "inline_scripts": [s[:MAX_INLINE_SCRIPT_CHARS] for s in inline[:MAX_INLINE_SCRIPTS]],
                "iframes": evaluate_all("iframe[src]", "els => els.map(e => e.src)"),
                "globals": page.evaluate(GLOBALS_SCRIPT, sorted(GLOBAL_NAMES)),
                "cookies_before_consent": cookies_before,
                "cookies": _cookies(context),
                "screenshot": page.screenshot(full_page=False, animations="disabled"),
            }
        finally:
            browser.close()
