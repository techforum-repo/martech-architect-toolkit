"""Screenshots of AEM author UI: a page's Page Properties or a component's
edit dialog (opened in the page editor), on the tab holding a value, with its field highlighted.

Taken in the signed-in AEM window (aem_browser): AEM's UI only trusts the
browser the user signed in with. This module has what runs in that window:
the field and tab search, tab opening, the capture itself, and the optional
no-saving rule (blocks_write). Nothing is clicked except dialog tabs, and
nothing is typed; the highlight is a style change in that browser only.
"""

from __future__ import annotations

import posixpath
from urllib.parse import quote, unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
FIELD_WAIT_SECONDS = 10
PROPERTIES_PATH = "/mnt/overlay/wcm/core/content/sites/properties.html"

# Finds form fields whose value contains the term, including fields on
# inactive and nested dialog tabs (custom tabs included), and returns each
# one with the tab path that leads to it.
FIND_FIELDS_SCRIPT = """([term, root]) => {
    const lowered = term.toLowerCase();
    // Only inside root (e.g. the open dialog in the page editor), if given.
    const scope = root ? document.querySelector(root) : document.body;
    if (!scope) return [];
    const PANEL = 'coral-panel, [role=tabpanel]';
    // The tab that shows a panel: AEM links them with aria-labelledby; otherwise
    // the tab at the same position in the panel's own tab group.
    // Returns [tab, how it was found], or [null, why not].
    const tabFor = panel => {
        const id = panel.getAttribute('aria-labelledby');
        if (id && document.getElementById(id)) return [document.getElementById(id), 'aria-labelledby'];
        // Or the tab pointing at the panel.
        const controller = panel.id && [...document.querySelectorAll('[aria-controls]')]
            .find(t => t.getAttribute('aria-controls') === panel.id && t.matches('coral-tab, [role=tab]'));
        if (controller) return [controller, 'aria-controls'];
        const panels = [...panel.parentElement.children].filter(c => c.matches(PANEL));
        let group = panel.parentElement;
        while (group && !group.querySelector(':scope > coral-tablist, :scope > [role=tablist]')) {
            group = group.parentElement;
        }
        if (!group) return [null, 'no tab list around the panel'];
        const list = group.querySelector(':scope > coral-tablist, :scope > [role=tablist]');
        const tabs = [...list.children].filter(c => c.matches('coral-tab, [role=tab]'));
        const tab = tabs[panels.indexOf(panel)];
        return tab ? [tab, 'position'] : [null, `panel ${panels.indexOf(panel) + 1} of ${panels.length}, ${tabs.length} tabs`];
    };
    // Where the field sits, innermost first: tag#id.class[role], for the details.
    const describe = element => {
        const parts = [];
        for (let e = element; e && e !== document.body && parts.length < 12; e = e.parentElement) {
            const cls = [...e.classList].slice(0, 2).map(c => '.' + c).join('');
            parts.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + cls
                       + (e.getAttribute('role') ? `[role=${e.getAttribute('role')}]` : ''));
        }
        return parts.join(' < ');
    };
    // Choices of a dropdown aren't its value, unless chosen.
    const unchosen = field => (field.matches('option') && !field.selected)
        || (field.matches('coral-select-item, coral-selectlist-item, coral-autocomplete-item')
            && !field.hasAttribute('selected'));
    const WRAPPER = '.coral-Form-fieldwrapper, .coral-Form-field, .foundation-field-edit';
    const results = [], seen = new Set();
    const add = (element, value, name, kind) => {
        if (seen.has(element)) return;  // several hidden inputs of one field
        seen.add(element);
        const wrapper = element.closest(WRAPPER) || element.parentElement;
        const label = wrapper && wrapper.querySelector('label, .coral-Form-fieldlabel');
        const tabs = [], how = [];
        for (let panel = element.closest(PANEL); panel; panel = panel.parentElement && panel.parentElement.closest(PANEL)) {
            const [tab, found] = tabFor(panel);
            how.unshift(found);
            if (tab) {
                tab.setAttribute('data-wti-tab', '');
                tabs.unshift(tab);  // outermost first
            }
        }
        if (!how.length) how.push('the field is in no tab panel');
        const marker = String(results.length);
        element.setAttribute('data-wti-match', marker);
        tabs.forEach((tab, depth) => tab.setAttribute('data-wti-tab-' + marker + '-' + depth, ''));
        results.push({marker, name, label: label ? label.textContent.trim() : '', kind,
                      value: value.slice(0, 300), tabs: tabs.map(t => t.textContent.trim()), depth: tabs.length,
                      found_by: how, where: describe(element)});
    };
    // 1. Field values, including hidden inputs: code editors and rich text keep
    // their value in one, shown by an editor next to it; that field is marked.
    scope.querySelectorAll('input, textarea, select, [value]').forEach(field => {
        const value = (field.value ?? field.getAttribute('value') ?? '').toString();
        if (!value.toLowerCase().includes(lowered) || unchosen(field)) return;
        const hidden = field.type === 'hidden';
        const shown = hidden ? field.closest(WRAPPER) : field;
        if (!shown) return;  // a hidden input outside any field: form state, not content
        add(shown, value, field.getAttribute('name') || '', hidden ? 'hidden value' : 'field');
    });
    // 2. Else any attribute (an editor may keep the value in e.g. data-value).
    if (!results.length) {
        for (const element of scope.querySelectorAll('*')) {
            if (results.length >= 10) break;
            if (element.closest('script, style, noscript, template')) continue;
            for (const attr of element.attributes) {
                if (!attr.name.startsWith('data-wti') && attr.value.toLowerCase().includes(lowered)) {
                    add(element.closest(WRAPPER) || element, attr.value, attr.name, 'attribute');
                    break;
                }
            }
        }
    }
    // 3. Else text in the dialog, e.g. as an editor displays it.
    if (!results.length) {
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node && results.length < 10; node = walker.nextNode()) {
            const element = node.parentElement;
            if (!element || element.closest('script, style, noscript, template, title')) continue;
            const text = node.textContent;
            const at = text.toLowerCase().indexOf(lowered);
            if (at < 0) continue;
            add(element.closest(WRAPPER) || element, text.slice(Math.max(0, at - 80), at + lowered.length + 80).trim(),
                '', 'text');
        }
    }
    return results;
}"""

# Selects one tab on a field's path through Coral itself, for when a click
# didn't (AEM's tabs may ignore clicks while still setting up).
SELECT_TAB_SCRIPT = """([marker, level]) => {
    const tab = document.querySelector(`[data-wti-tab-${marker}-${level}]`);
    if (!tab) return false;
    tab.selected = true;  // Coral's coral-tab
    tab.setAttribute('aria-selected', 'true');
    const panel = document.getElementById(tab.getAttribute('aria-controls') || '');
    if (panel) panel.selected = true;  // Coral's coral-panel
    return true;
}"""

# Highlights the field and scrolls it into view.
SHOW_FIELD_SCRIPT = """marker => {
    const field = document.querySelector(`[data-wti-match="${marker}"]`);
    if (!field) return false;
    const box = field.closest('.coral-Form-fieldwrapper, .coral-Form-field') || field;
    box.scrollIntoView({block: 'center'});
    box.style.outline = '4px solid #e8710a';
    box.style.outlineOffset = '4px';
    return true;
}"""

# When nothing matched: what the dialog has, to say why.
NO_MATCH_SCRIPT = """([term, root]) => {
    const scope = (root ? document.querySelector(root) : document.documentElement) || document.createElement('div');
    return {
        tabs: [...scope.querySelectorAll('coral-tab, [role=tab]')].map(t => t.textContent.trim()).filter(Boolean).slice(0, 40),
        fields: scope.querySelectorAll('input, textarea, select').length,
        in_html: scope.outerHTML.toLowerCase().includes(term.toLowerCase()),
    };
}"""

# The page editor: its open component dialog, and whether its editables are loaded.
EDITOR_DIALOG = "coral-dialog.is-open, coral-dialog[open], .cq-Dialog.is-open"
EDITOR_READY_SCRIPT = """() => !!(window.Granite && Granite.author && Granite.author.editables
                                  && Granite.author.editables.length)"""

# Opens a component's edit dialog the way the editor's wrench button does,
# through AEM's own editor API: "opened", "not-found" or "no-api".
OPEN_DIALOG_SCRIPT = """path => {
    const author = Granite.author;
    try {  // the Edit layer has the dialogs (the editor may open in Preview)
        if (author.layerManager.getCurrentLayerName() !== 'Edit') author.layerManager.activateLayer('Edit');
    } catch (e) {}
    let editable = null;
    try { const found = author.editables.find(path); editable = Array.isArray(found) ? found[0] : found; } catch (e) {}
    if (!editable || editable.path !== path) {
        try { editable = [...author.editables].find(e => e && e.path === path) || null; } catch (e) { editable = null; }
    }
    if (!editable) return 'not-found';
    try { author.DialogFrame.openDialog(new author.edit.Dialog(editable)); return 'opened'; } catch (e) {}
    try { author.edit.EditableActions.CONFIGURE.execute(editable); return 'opened'; } catch (e) {}
    return 'no-api';
}"""

# The tabs showing now, for the details.
SHOWN_TABS_SCRIPT = """root => [...((root && document.querySelector(root)) || document).querySelectorAll('coral-tab, [role=tab]')]
    .filter(t => t.selected === true || t.getAttribute('aria-selected') === 'true' || t.hasAttribute('selected'))
    .map(t => t.textContent.trim())"""

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


def properties_url(author_base: str, page_path: str) -> str:
    return author_base.rstrip("/") + PROPERTIES_PATH + "?item=" + quote(page_path, safe="/:")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


# Where a POST changes the repository: the Sling POST servlet saves to any
# node under these roots (how dialogs and Page Properties save), and these
# servlets publish, move, delete, run workflows or roll out.
SAVE_ROOTS = ("/content", "/conf", "/apps", "/libs", "/etc", "/var", "/home", "/oak:index", "/jcr:system")
SAVE_SERVLETS = ("/bin/", "/adobe/", "/api/")
# Read-only POSTs under those roots: AEM's GraphQL has queries only.
READ_POSTS = ("/content/cq:graphql/", "/content/_cq_graphql/")


def _path(url: str) -> str:
    # Decoded and normalised, so /%63ontent or /x/../content still count.
    # normpath keeps a leading "//", which Sling treats as "/".
    return "/" + posixpath.normpath("/" + unquote(urlsplit(url).path)).lower().lstrip("/")


def blocks_write(method: str, url: str, author_base: str) -> bool:
    """The no-save rule: no request that changes content reaches author.

    Only the author origin is guarded. AEM's UI also POSTs to Adobe's sign-in
    service to keep its login fresh; blocking that made AEM send the browser to
    Adobe sign-in, and it can't change anything in AEM.

    Not every POST is a save: AEM's UI makes some while it loads, and blocking
    them all stopped the start page and dialogs loading. So PUT, PATCH and
    DELETE are always blocked, and POST wherever it saves (see SAVE_ROOTS)."""
    method = method.upper()
    if method in READ_METHODS or _origin(url) != _origin(author_base):
        return False
    if method != "POST":
        return True
    path = _path(url)
    if any(path.startswith(root) for root in READ_POSTS) and path.endswith(".json"):
        return False
    return any(path == root or path.startswith(root + "/") or path.startswith(root + ".")
               for root in SAVE_ROOTS) or any(path.startswith(s) for s in SAVE_SERVLETS)


def _find_fields(page, term: str, root: str | None = None):
    """(frame, matches): the dialog's own page first, then any frame in it."""
    for frame in page.frames:
        try:
            fields = frame.evaluate(FIND_FIELDS_SCRIPT, [term, root])
        except PlaywrightError:
            continue  # a frame that went away or can't be read
        if fields:
            return frame, fields
    return page.main_frame, []


def _no_match(page, term: str, root: str | None = None) -> dict:
    """What the dialog has, when nothing in it matched the term."""
    found = {"tabs": [], "fields": 0, "in_html": False, "frames": len(page.frames) - 1}
    for frame in page.frames:
        try:
            info = frame.evaluate(NO_MATCH_SCRIPT, [term, root])
        except PlaywrightError:
            continue
        found["tabs"] += info["tabs"]
        found["fields"] += info["fields"]
        found["in_html"] = found["in_html"] or info["in_html"]
    return found


def _open_tabs(page, marker: str, depth: int) -> None:
    """Open the tabs leading to a field, outermost first: a real mouse click
    on each, as a person would; then, if the field still isn't showing,
    select them through Coral instead."""
    for level in range(depth):
        try:
            page.locator(f"[data-wti-tab-{marker}-{level}]").first.click(timeout=3000)
        except PlaywrightError:
            page.evaluate(SELECT_TAB_SCRIPT, [marker, level])
        page.wait_for_timeout(300)
    if depth and not page.evaluate(FIELD_VISIBLE_SCRIPT, marker):
        for level in range(depth):
            page.evaluate(SELECT_TAB_SCRIPT, [marker, level])
            page.wait_for_timeout(300)


class DialogNotOpened(RuntimeError):
    """The page editor didn't open the component's dialog."""


def _settle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(500)  # a sign-in redirect may happen in script


def _require_author(page, author_base: str, blocked: list[str], what: str) -> None:
    """Raise AemLoginRequired unless the tab is still on author."""
    landed = page.url.lower()
    sign_in_page = _is_sign_in_page(landed)
    if sign_in_page or not landed.startswith(author_base.lower().rstrip("/")):
        where = page.url.split("?")[0]
        raise AemLoginRequired(
            f"The {what} opened {'a sign-in page' if sign_in_page else 'a different page'} "
            f"instead: {where}", landed=where, title=page.title(), sign_in_page=sign_in_page,
            blocked=list(blocked))


def _capture_in_page(page, author_base: str, urls: list[str], term: str, blocked: list[str],
                     timeout: int) -> dict:
    """In an already open tab: open the first of urls that renders (Page
    Properties), then screenshot each field containing term."""
    url, response, attempts = urls[0], None, []
    for url in urls:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        attempts.append({"url": url, "status": response.status if response else None})
        if not response or response.status < 400:
            break
    _settle(page)
    _require_author(page, author_base, blocked, "dialog")
    return _capture_matches(page, term, url, response.status if response else None, attempts, blocked)


def editor_url(author_base: str, page_path: str) -> str:
    return author_base.rstrip("/") + "/editor.html" + quote(page_path, safe="/:") + ".html"


def _capture_in_editor(page, author_base: str, node_path: str, term: str, blocked: list[str],
                       timeout: int) -> dict:
    """A component's dialog as authors open it: the page in the page editor,
    then that component's dialog (AEM doesn't open component dialogs at an
    address of their own the way it does Page Properties), then the matches
    inside the dialog only."""
    page_path = node_path.split("/jcr:content", 1)[0]
    url = editor_url(author_base, page_path)
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    attempts = [{"url": url, "status": response.status if response else None}]
    _settle(page)
    _require_author(page, author_base, blocked, "page editor")
    try:
        page.wait_for_function(EDITOR_READY_SCRIPT, timeout=timeout * 1000)
    except PlaywrightTimeout as exc:
        raise DialogNotOpened(f"The page editor for {page_path} didn't finish loading its components") from exc

    opened = page.evaluate(OPEN_DIALOG_SCRIPT, node_path)
    if opened == "not-found":
        raise DialogNotOpened(f"The page editor of {page_path} has no editable component at {node_path} "
                              "(it may come from the template or a locked structure).")
    if opened == "no-api":
        # As an author would: select the component, then the wrench (Configure).
        try:
            page.locator(f'.cq-Overlay[data-path="{node_path}"]').first.click(timeout=10_000)
            page.locator('button[data-action="CONFIGURE"]').first.click(timeout=10_000)
        except PlaywrightError as exc:
            raise DialogNotOpened(f"Couldn't open the dialog of {node_path} in the page editor") from exc
    try:
        page.wait_for_selector(EDITOR_DIALOG, state="visible", timeout=30_000)
    except PlaywrightTimeout as exc:
        raise DialogNotOpened(f"The dialog of {node_path} didn't open in the page editor") from exc
    page.wait_for_timeout(500)  # the dialog's opening animation
    return _capture_matches(page, term, url, attempts[0]["status"], attempts, blocked, root=EDITOR_DIALOG)


def _capture_matches(page, term: str, url: str, status, attempts: list[dict], blocked: list[str],
                     root: str | None = None) -> dict:
    """Screenshot each field containing term (only inside root, if given),
    on its tab."""
    frame, fields = _find_fields(page, term, root)
    for _ in range(FIELD_WAIT_SECONDS):  # AEM's UI may still be building the form
        if fields:
            break
        page.wait_for_timeout(1000)
        frame, fields = _find_fields(page, term, root)
    captured = []
    for field in fields[:10]:
        _open_tabs(frame, field["marker"], field["depth"])
        if frame.evaluate(SHOW_FIELD_SCRIPT, field["marker"]):
            page.wait_for_timeout(300)  # scroll
            captured.append({
                "label": field["label"], "name": field["name"], "value": field["value"],
                "tabs": field["tabs"], "visible": frame.evaluate(FIELD_VISIBLE_SCRIPT, field["marker"]),
                "found_by": field["found_by"], "where": field["where"], "kind": field["kind"],
                "shown_tabs": frame.evaluate(SHOWN_TABS_SCRIPT, root),
                "image": page.screenshot(full_page=False, animations="disabled"),
            })

    return {
        "url": url,
        "status": status,
        "attempts": attempts,
        "fields": captured,
        "page_image": None if captured else page.screenshot(full_page=False, animations="disabled"),
        "no_match": None if captured else _no_match(page, term, root),
        "blocked_writes": list(blocked),
    }
