"""Screenshots of AEM author UI, e.g. a page's Page Properties with the
field that holds a value highlighted.

Read-only by construction, because author UI pages run their own scripts:
- every request that isn't GET, HEAD or OPTIONS is aborted, on any host;
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
# inactive dialog tabs, and returns where each one is.
FIND_FIELDS_SCRIPT = """term => {
    const lowered = term.toLowerCase();
    const fields = [...document.querySelectorAll('input, textarea, select, [value]')];
    const results = [];
    fields.forEach((field, index) => {
        const value = (field.value ?? field.getAttribute('value') ?? '').toString();
        if (!value.toLowerCase().includes(lowered) || field.type === 'hidden') return;
        const wrapper = field.closest('.coral-Form-fieldwrapper, .coral-Form-field, .foundation-field-edit') || field.parentElement;
        const label = wrapper && wrapper.querySelector('label, .coral-Form-fieldlabel');
        const panel = field.closest('coral-panel, [role=tabpanel]');
        let tab = -1;
        if (panel && panel.parentElement) {
            tab = [...panel.parentElement.children].filter(c => c.matches('coral-panel, [role=tabpanel]')).indexOf(panel);
        }
        field.setAttribute('data-wti-match', String(index));
        results.push({marker: String(index), name: field.getAttribute('name') || '',
                      label: label ? label.textContent.trim() : '', value: value.slice(0, 300), tab});
    });
    return results;
}"""

SHOW_FIELD_SCRIPT = """([marker, tab]) => {
    if (tab >= 0) {
        const tabs = [...document.querySelectorAll('coral-tab, [role=tab]')];
        if (tabs[tab]) tabs[tab].click();
    }
    const field = document.querySelector(`[data-wti-match="${marker}"]`);
    if (!field) return false;
    const box = field.closest('.coral-Form-fieldwrapper, .coral-Form-field') || field;
    box.scrollIntoView({block: 'center'});
    box.style.outline = '4px solid #e8710a';
    box.style.outlineOffset = '4px';
    return true;
}"""


class AemLoginRequired(RuntimeError):
    """Author redirected to its login page: the token isn't accepted for UI pages."""


def properties_url(author_base: str, page_path: str) -> str:
    return author_base.rstrip("/") + PROPERTIES_PATH + "?item=" + quote(page_path, safe="/")


def _guard(context, author_base: str, token: str, blocked: list[str]) -> None:
    author = urlsplit(author_base)
    origin = f"{author.scheme}://{author.netloc}".lower()

    def handle(route):
        request = route.request
        if request.method.upper() not in READ_METHODS:
            blocked.append(f"{request.method} {request.url}")
            route.abort()
            return
        url = urlsplit(request.url)
        if f"{url.scheme}://{url.netloc}".lower() == origin:
            route.fallback(headers={**request.headers, "authorization": "Bearer " + token})
        else:
            route.fallback()

    context.route("**/*", handle)


def capture_page_properties(author_base: str, page_path: str, term: str, token: str, *,
                            show_browser: bool = False, timeout: int = 60,
                            prepare_context=None) -> dict:
    """Open Page Properties for the page and screenshot each field containing term.

    Returns {"url", "fields": [{"label", "name", "value", "image"}], "page_image",
    "blocked_writes"}. Raises AemLoginRequired when author shows its login page.
    prepare_context: test hook to serve a fixture author (registered first, so
    the read-only guard still runs in front of it).
    """
    url = properties_url(author_base, page_path)
    blocked: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not show_browser)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                          service_workers="block", accept_downloads=False)
            if prepare_context:
                prepare_context(context)
            _guard(context, author_base, token, blocked)  # registered last: runs first
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(500)  # a sign-in redirect may happen in script

            landed = page.url.lower()
            if "login" in landed or "ims" in urlsplit(landed).netloc or not landed.startswith(author_base.lower()):
                raise AemLoginRequired(f"Author showed its sign-in page instead ({page.url.split('?')[0]})")

            fields = page.evaluate(FIND_FIELDS_SCRIPT, term)
            captured = []
            for field in fields[:10]:
                if page.evaluate(SHOW_FIELD_SCRIPT, [field["marker"], field["tab"]]):
                    page.wait_for_timeout(300)  # tab switch and scroll
                    captured.append({
                        "label": field["label"], "name": field["name"], "value": field["value"],
                        "image": page.screenshot(full_page=False, animations="disabled"),
                    })

            return {
                "url": url,
                "fields": captured,
                "page_image": None if captured else page.screenshot(full_page=False, animations="disabled"),
                "blocked_writes": blocked,
            }
        finally:
            browser.close()
