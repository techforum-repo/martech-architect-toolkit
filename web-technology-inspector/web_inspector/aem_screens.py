"""Screenshots of AEM author UI, e.g. a page's Page Properties with the
field that holds a value highlighted.

Authors that don't accept the AEM token for UI pages need a one-time
sign-in (sign_in): a visible browser opens on author, the user logs in as
usual, and the resulting browser session is reused for screenshots. That
session works like a password, so callers keep it in memory only.

Read-only by construction, because author UI pages run their own scripts:
- every request to author that isn't GET, HEAD or OPTIONS is aborted;
- the AEM token is added only to requests to the author origin, never to
  the CDNs and other hosts the UI loads;
- nothing is clicked except dialog tabs, and nothing is typed.
The highlight is a style change in this browser only.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
PROPERTIES_PATH = "/mnt/overlay/wcm/core/content/sites/properties.html"

# Finds form fields whose value contains the term, including fields on
# inactive and nested dialog tabs (custom tabs included), and returns each
# one with the tab path that leads to it.
FIND_FIELDS_SCRIPT = """term => {
    const lowered = term.toLowerCase();
    const PANEL = 'coral-panel, [role=tabpanel]';
    // The tab that shows a panel: AEM links them with aria-labelledby; otherwise
    // the tab at the same position in the panel's own tab group.
    const tabFor = panel => {
        const id = panel.getAttribute('aria-labelledby');
        if (id && document.getElementById(id)) return document.getElementById(id);
        const panels = [...panel.parentElement.children].filter(c => c.matches(PANEL));
        let group = panel.parentElement;
        while (group && !group.querySelector(':scope > coral-tablist, :scope > [role=tablist]')) {
            group = group.parentElement;
        }
        if (!group) return null;
        const list = group.querySelector(':scope > coral-tablist, :scope > [role=tablist]');
        const tabs = [...list.children].filter(c => c.matches('coral-tab, [role=tab]'));
        return tabs[panels.indexOf(panel)] || null;
    };
    const results = [];
    const fields = [...document.querySelectorAll('input, textarea, select, [value]')];
    fields.forEach((field, index) => {
        const value = (field.value ?? field.getAttribute('value') ?? '').toString();
        if (!value.toLowerCase().includes(lowered) || field.type === 'hidden') return;
        const wrapper = field.closest('.coral-Form-fieldwrapper, .coral-Form-field, .foundation-field-edit') || field.parentElement;
        const label = wrapper && wrapper.querySelector('label, .coral-Form-fieldlabel');
        const tabs = [];
        for (let panel = field.closest(PANEL); panel; panel = panel.parentElement && panel.parentElement.closest(PANEL)) {
            const tab = tabFor(panel);
            if (tab) {
                tab.setAttribute('data-wti-tab', '');
                tabs.unshift(tab);  // outermost first
            }
        }
        const marker = String(index);
        field.setAttribute('data-wti-match', marker);
        tabs.forEach((tab, depth) => tab.setAttribute('data-wti-tab-' + marker + '-' + depth, ''));
        results.push({marker, name: field.getAttribute('name') || '', label: label ? label.textContent.trim() : '',
                      value: value.slice(0, 300), tabs: tabs.map(t => t.textContent.trim()), depth: tabs.length});
    });
    return results;
}"""

# Opens each tab on the path, outermost first, then highlights the field.
SHOW_FIELD_SCRIPT = """([marker, depth]) => {
    for (let level = 0; level < depth; level++) {
        const tab = document.querySelector(`[data-wti-tab-${marker}-${level}]`);
        if (tab) tab.click();
    }
    const field = document.querySelector(`[data-wti-match="${marker}"]`);
    if (!field) return false;
    const box = field.closest('.coral-Form-fieldwrapper, .coral-Form-field') || field;
    box.scrollIntoView({block: 'center'});
    box.style.outline = '4px solid #e8710a';
    box.style.outlineOffset = '4px';
    return true;
}"""

# Whether the highlighted field is actually showing (not on a hidden tab).
FIELD_VISIBLE_SCRIPT = """marker => {
    const field = document.querySelector(`[data-wti-match="${marker}"]`);
    if (!field) return false;
    const box = field.getBoundingClientRect();
    return field.getClientRects().length > 0 && box.width > 0 && box.height > 0;
}"""


class AemLoginRequired(RuntimeError):
    """Page Properties didn't open on author: it went to a sign-in page, or elsewhere.

    landed: where the browser ended up. sign_in_page: True when that looks
    like a sign-in page (the session isn't accepted or has ended), False when
    author sent the browser somewhere else (e.g. the Experience Cloud shell).
    """

    def __init__(self, message: str, *, landed: str = "", title: str = "", sign_in_page: bool = True,
                 blocked: list[str] | None = None):
        super().__init__(message)
        self.landed = landed
        self.title = title
        self.sign_in_page = sign_in_page
        self.blocked = blocked or []


def _is_sign_in_page(url: str) -> bool:
    """An Adobe sign-in host, or AEM's own login path; never decided by the
    page path being opened (passed in the query string)."""
    parts = urlsplit(url.lower())
    return (
        "adobelogin." in parts.netloc
        or parts.netloc.startswith(("ims-", "ims."))
        or (parts.netloc.startswith("auth.") and parts.netloc.endswith(".adobe.com"))
        or "/login" in parts.path
        or "j_security_check" in parts.path
    )


class SignInIncomplete(RuntimeError):
    """The sign-in window was closed, or the time ran out, before author was reached."""


def _signed_in(page, context, author_base: str) -> bool:
    author_host = urlsplit(author_base).hostname
    on_author = page.url.lower().startswith(author_base.lower().rstrip("/")) and not _is_sign_in_page(page.url)
    has_session = any(
        c["name"] == "login-token" and author_host.endswith(c["domain"].lstrip("."))
        for c in context.cookies()
    )
    return on_author and has_session


def sign_in(author_base: str, *, timeout: int = 300, show_browser: bool = True,
            prepare_context=None) -> dict:
    """Open author in a browser, wait for the user to log in, return the session.

    Returns Playwright storage state (cookies) plus "user_agent", for reuse
    in capture calls: Adobe's sign-in may not accept the session from a
    browser that identifies itself differently (e.g. as HeadlessChrome).
    The window closes by itself once author is reached with a login session.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not show_browser)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            if prepare_context:
                prepare_context(context)
            page = context.new_page()
            page.goto(author_base.rstrip("/") + "/aem/start.html", wait_until="domcontentloaded",
                      timeout=60_000)
            for _ in range(timeout):
                if page.is_closed():
                    raise SignInIncomplete("The sign-in window was closed before signing in")
                if _signed_in(page, context, author_base):
                    try:  # let author finish its post-login requests and cookies
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightTimeout:
                        pass
                    return dict(context.storage_state(), user_agent=page.evaluate("navigator.userAgent"))
                page.wait_for_timeout(1000)
            raise SignInIncomplete(f"Not signed in within {timeout // 60} minutes")
        finally:
            browser.close()


def properties_url(author_base: str, page_path: str) -> str:
    return author_base.rstrip("/") + PROPERTIES_PATH + "?item=" + quote(page_path, safe="/:")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def blocks_write(method: str, url: str, author_base: str) -> bool:
    """The read-only rule: no request that could change content reaches author.

    Only the author origin is guarded. AEM's UI also POSTs to Adobe's sign-in
    service to keep its login fresh; blocking that made AEM send the browser to
    Adobe sign-in, and it can't change anything in AEM."""
    return method.upper() not in READ_METHODS and _origin(url) == _origin(author_base)


def _guard(context, author_base: str, token: str | None, blocked: list[str]) -> None:
    origin = _origin(author_base)

    def handle(route):
        request = route.request
        if blocks_write(request.method, request.url, author_base):
            blocked.append(f"{request.method} {request.url}")
            route.abort()
            return
        if token and _origin(request.url) == origin:
            route.fallback(headers={**request.headers, "authorization": "Bearer " + token})
        else:
            route.fallback()

    context.route("**/*", handle)


def component_dialog_urls(author_base: str, node_path: str, resource_type: str) -> list[str]:
    """Addresses of a component instance's edit dialog, as the page editor opens it.

    The resource type resolves under /apps or /libs, so both are tried
    (the one it names first, if it is absolute)."""
    rt = resource_type.strip()
    roots = ["apps", "libs"]
    for root in ("/apps/", "/libs/"):
        if rt.startswith(root):
            rt = rt[len(root):]
            roots = [root.strip("/")] + [r for r in roots if r != root.strip("/")]
    rt = rt.strip("/")
    base = author_base.rstrip("/")
    # ":" stays literal (jcr:content), as in the addresses the page editor uses.
    return [f"{base}/mnt/override/{root}/{quote(rt, safe='/')}/_cq_dialog.html{quote(node_path, safe='/:')}"
            for root in roots]


def _identity(storage_state: dict | None, browser_version: str) -> tuple[dict | None, str]:
    """(storage state for Playwright, user agent): the sign-in browser's agent
    if known, else a regular, non-headless Chrome agent."""
    from .scanner import _desktop_user_agent
    if not storage_state:
        return None, _desktop_user_agent(browser_version)
    state = {k: v for k, v in storage_state.items() if k in ("cookies", "origins")}
    return state, storage_state.get("user_agent") or _desktop_user_agent(browser_version)


def _capture_in_page(page, author_base: str, urls: list[str], term: str, blocked: list[str],
                     timeout: int) -> dict:
    """In an already open tab: open the first of urls that renders, then
    screenshot each field containing term."""
    url, response, attempts = urls[0], None, []
    for url in urls:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        attempts.append({"url": url, "status": response.status if response else None})
        # A wrong /apps vs /libs guess can answer 404 or 500: try the next address.
        if not response or response.status < 400:
            break
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(500)  # a sign-in redirect may happen in script

    landed = page.url.lower()
    sign_in_page = _is_sign_in_page(landed)
    if sign_in_page or not landed.startswith(author_base.lower().rstrip("/")):
        where = page.url.split("?")[0]
        raise AemLoginRequired(
            f"The dialog opened {'a sign-in page' if sign_in_page else 'a different page'} "
            f"instead: {where}", landed=where, title=page.title(), sign_in_page=sign_in_page,
            blocked=list(blocked))

    fields = page.evaluate(FIND_FIELDS_SCRIPT, term)
    captured = []
    for field in fields[:10]:
        if page.evaluate(SHOW_FIELD_SCRIPT, [field["marker"], field["depth"]]):
            page.wait_for_timeout(300 + 200 * field["depth"])  # tab switches and scroll
            captured.append({
                "label": field["label"], "name": field["name"], "value": field["value"],
                "tabs": field["tabs"], "visible": page.evaluate(FIELD_VISIBLE_SCRIPT, field["marker"]),
                "image": page.screenshot(full_page=False, animations="disabled"),
            })

    return {
        "url": url,
        "status": response.status if response else None,
        "attempts": attempts,
        "fields": captured,
        "page_image": None if captured else page.screenshot(full_page=False, animations="disabled"),
        "blocked_writes": list(blocked),
    }


def _capture_dialogs(author_base: str, urls: list[str], term: str, token: str | None, *,
                     show_browser: bool, timeout: int, storage_state: dict | None, prepare_context) -> dict:
    """In a new browser: open the first of urls that renders and screenshot matching fields."""
    blocked: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not show_browser)
        try:
            state, user_agent = _identity(storage_state, browser.version)
            context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                          service_workers="block", accept_downloads=False,
                                          storage_state=state, user_agent=user_agent)
            if prepare_context:
                prepare_context(context)
            _guard(context, author_base, token, blocked)  # registered last: runs first
            return _capture_in_page(context.new_page(), author_base, urls, term, blocked, timeout)
        finally:
            browser.close()


def capture_page_properties(author_base: str, page_path: str, term: str, token: str | None, *,
                            show_browser: bool = False, timeout: int = 60,
                            storage_state: dict | None = None, prepare_context=None) -> dict:
    """Open Page Properties for the page and screenshot each field containing term.

    Authenticates with the AEM token, or with a sign_in() session passed as
    storage_state (token may then be None).

    Returns {"url", "status", "fields": [{"label", "name", "value", "image"}],
    "page_image", "blocked_writes"}. Raises AemLoginRequired when the dialog
    doesn't open on author. prepare_context: test hook to serve a fixture
    author (registered first, so the read-only guard still runs in front of it).
    """
    return _capture_dialogs(author_base, [properties_url(author_base, page_path)], term, token,
                            show_browser=show_browser, timeout=timeout, storage_state=storage_state,
                            prepare_context=prepare_context)


def capture_component_dialog(author_base: str, node_path: str, resource_type: str, term: str,
                             token: str | None, *, show_browser: bool = False, timeout: int = 60,
                             storage_state: dict | None = None, prepare_context=None) -> dict:
    """Open one component instance's edit dialog and screenshot each field containing term.

    Same result and errors as capture_page_properties."""
    return _capture_dialogs(author_base, component_dialog_urls(author_base, node_path, resource_type), term,
                            token, show_browser=show_browser, timeout=timeout, storage_state=storage_state,
                            prepare_context=prepare_context)
