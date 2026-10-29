"""Inspect one page: scan it, then explore technologies, third parties,
consent, attribution and AEM evidence."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from .. import aem_browser, aem_lookup, aem_mock, database, mock_scan, site_credentials
from ..aem_screens import AemLoginRequired, capture_component_dialog, capture_page_properties
from ..errors import friendly_error
from ..config import settings
from ..detection import EXPECTED_BEFORE_CONSENT, aem_code_folders, consent_violations
from ..investigation import analyze_target, environment_auth, lookup_aem_page, needs_sign_in, run_investigation
from ..report import build_report, dot_graph, html_report, request_graph, requests_csv, stage_label
from ..site_config import load, match
from ..targets import available_targets
from .shared import megabytes, show_error, sign_in_to_aem

CONSENT_MODES = {
    "Leave the consent banner alone": "none",
    "Accept consent, and compare before / after": "accept",
}


def _configuration(mock: bool) -> tuple[list[dict], list[dict]]:
    if mock:
        return [aem_mock.MAPPING], [aem_mock.ENVIRONMENT]
    return load("aem_mappings.json", "mappings"), load("aem_environments.json", "environments")


def _run_form(mappings: list[dict], mock: bool) -> None:
    url = st.text_input(
        "Website URL",
        key="inspect_url_mock" if mock else "inspect_url",
        value=mock_scan.PAGE if mock else "",
        placeholder="https://www.example.com/en/page.html",
    )
    col1, col2, col3 = st.columns([1, 2, 1])
    device = col1.radio("Device", ["desktop", "mobile"], horizontal=True, format_func=str.title)
    consent = CONSENT_MODES[col2.radio("Consent", list(CONSENT_MODES), horizontal=True)]
    show_browser = col3.checkbox(
        "Show browser",
        value=settings.show_browser,
        disabled=mock,
        help="Opens a visible Chrome window. Use it when a site blocks the hidden (headless) browser.",
    )

    known_domain = url and any(
        m["published_domain"].lower() in url.lower() for m in mappings
    )
    if url and not (match(url, mappings) or known_domain):
        st.warning("No website mapping for this domain. Add one under Settings.")

    login = None
    if url and known_domain and not mock:
        login, source = site_credentials.resolve(
            urlsplit(url).hostname or "", st.session_state["session_site_credentials"])
        if login:
            st.caption(f"Signing in to the site as {login['username']} (Basic authentication, {source}).")

    if st.button("Run investigation", type="primary", disabled=not (url and known_domain)):
        with st.spinner("Scanning the page" + (" (a browser window will open)" if show_browser else "") + "..."):
            result = run_investigation(
                url, *_configuration(mock), mock=mock, device=device, consent=consent,
                show_browser=show_browser, timeout=settings.scan_timeout,
                settle=settings.settle_seconds, session_tokens=st.session_state["session_aem_tokens"],
                ui_sessions=st.session_state["aem_ui_sessions"], site_login=login,
            )
        result["consent_mode"] = consent
        if result.get("browser"):
            result["scan_id"] = database.save_scan(result, consent)
        st.session_state["result"] = result
        st.session_state["analysis_cache"] = {}


def _environment_for(url: str, mappings: list[dict], environments: list[dict]) -> dict | None:
    host = (urlsplit(url).hostname or "").lower() if url else ""
    mapping = next((m for m in mappings if m["published_domain"].lower() == host), None)
    if not mapping:
        return None
    return next((e for e in environments if e["id"] == mapping["environment_id"]), None)


def _after_sign_in() -> None:
    """Redo whatever was waiting for the sign-in: the scan's AEM stage, then screenshots."""
    result = st.session_state.get("result")
    if result and result.get("environment") and needs_sign_in(result):
        lookup_aem_page(result, session_tokens=st.session_state["session_aem_tokens"],
                        ui_sessions=st.session_state["aem_ui_sessions"])
        st.session_state["analysis_cache"] = {}
    captures = st.session_state.get("properties_captures")
    if result and captures and any(item.get("sign_in") for item in captures["items"]):
        _capture_pages(result, captures["targets"], captures["key"][1], captures["key"])


def _aem_connection(mappings: list[dict], environments: list[dict], mock: bool) -> None:
    """The single place to see and set up the AEM connection."""
    if mock:
        st.caption("AEM: sample author (mock mode), no sign-in needed.")
        return
    environment = _environment_for(st.session_state.get("inspect_url", ""), mappings, environments)
    if not environment:
        return
    auth = environment_auth(environment, st.session_state["session_aem_tokens"],
                            st.session_state["aem_ui_sessions"])
    col1, col2 = st.columns([4, 1])
    if auth["method"] == "sign-in" and aem_browser.get_window(environment["id"]):
        col1.success(f"Signed in to AEM ({environment['name']}). Keep the AEM window open for screenshots.")
    elif auth["method"] == "sign-in":
        col1.info(f"Signed in to AEM ({environment['name']}) for lookups. The AEM window was closed: "
                  "sign in again for screenshots.")
    elif auth["method"] == "token":
        col1.info(f"Connected to AEM ({environment['name']}) with a token. Sign in instead for screenshots.")
    else:
        col1.warning(f"Not signed in to AEM ({environment['name']}). Sign in to find the AEM page, "
                     "search AEM and take screenshots.")
    window_open = aem_browser.get_window(environment["id"]) is not None
    if not (auth["method"] == "sign-in" and window_open) and \
            col2.button("Sign in to AEM", type="primary", key="aem_sign_in"):
        if sign_in_to_aem(environment):
            _after_sign_in()
            st.rerun()


def _changes(result: dict) -> None:
    scan_id = result.get("scan_id")
    previous = database.previous_scan(scan_id) if scan_id else None
    if not previous:
        return
    current = database.get_scan(scan_id)
    diff = database.compare(previous["summary"], current["summary"])
    changed = {k: v for k, v in diff.items() if v["added"] or v["removed"]}
    label = f"Changes since the previous scan ({previous['scanned_at'][:16].replace('T', ' ')} UTC)"
    with st.expander(label + ("" if changed else ": none"), expanded=bool(changed)):
        for key, value in changed.items():
            st.markdown(f"**{key.replace('_', ' ').capitalize()}**")
            for item in value["added"]:
                st.markdown(f"- ➕ {item}")
            for item in value["removed"]:
                st.markdown(f"- ➖ {item}")


def _overview(result: dict, browser: dict) -> None:
    third_party = [d for d in result["domains"] if not d["first_party"]]
    cols = st.columns(5)
    cols[0].metric("Requests", len(browser["requests"]))
    cols[1].metric("Technologies", len(result["technologies"]))
    cols[2].metric("Third-party domains", len(third_party))
    cols[3].metric("Third-party weight", megabytes(sum(d["bytes"] for d in third_party)))
    if result.get("consent_mode") == "accept":
        cols[4].metric("Tracked before consent", len(consent_violations(result["domains"])),
                       help="Third-party domains contacted before consent, not counting the "
                            "consent tool and tag manager, which have to load first")
    else:
        cols[4].metric("Device", browser.get("device", "").title())


def _technologies_tab(result: dict) -> None:
    if not result["technologies"]:
        st.info("No known technology signatures detected.")
        return
    st.dataframe(pd.DataFrame([
        {"Technology": t["technology"], "Category": t["category"], "Evidence": t["confidence"],
         "Examples": ", ".join(t["evidence"][:3])}
        for t in result["technologies"]
    ]), width="stretch", hide_index=True)


def _third_parties_tab(result: dict, browser: dict) -> None:
    rows = [
        {"Domain": d["domain"], "Technology": d["technology"], "Party": "First" if d["first_party"] else "Third",
         "Requests": d["requests"], "Transferred": megabytes(d["bytes"]), "Total time (ms)": d["total_ms"],
         "Before consent": d["before_consent"], "Failed": d["failed"]}
        for d in result["domains"]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("Transfer size and time come from the browser and include compression and caching effects.")
    with st.expander("All requests"):
        st.dataframe(pd.DataFrame([
            {"URL": r["url"], "Type": r["type"], "Status": r["status"], "Bytes": r["bytes"],
             "ms": r["duration_ms"], "Phase": r["phase"], "Initiator": r["initiator_url"],
             "Redirect": r["redirected_to"] or r["redirect_from"], "Failed": r["failed"]}
            for r in browser["requests"]
        ]), width="stretch", hide_index=True)


def _consent_tab(result: dict, browser: dict) -> None:
    consent = browser.get("consent") or {}
    if consent.get("mode") != "accept":
        st.info("Run with “Accept consent, and compare before / after” to audit consent.")
    elif not consent.get("accepted"):
        st.warning("No known consent banner was found, so nothing was accepted. "
                   "Everything below loaded without an explicit consent click.")
    else:
        st.success(f"Accepted the {consent['platform']} banner during the scan.")
        early = [d for d in result["domains"] if d["before_consent"] and not d["first_party"]]
        st.subheader("Third parties contacted before consent")
        if early:
            st.dataframe(pd.DataFrame([
                {"Domain": d["domain"], "Technology": d["technology"],
                 "Requests before consent": d["before_consent"],
                 "Assessment": ("Expected: " + d["category"].lower()
                                if d.get("category") in EXPECTED_BEFORE_CONSENT else "Review")}
                for d in early
            ]), width="stretch", hide_index=True)
        else:
            st.success("None. No third-party requests were made before consent.")

    before = {(c["name"], c["domain"]) for c in browser.get("cookies_before_consent") or []}
    st.subheader("Cookies")
    st.dataframe(pd.DataFrame([
        {"Name": c["name"], "Domain": c["domain"],
         "Set": "Before consent" if (c["name"], c["domain"]) in before else
                ("After consent" if consent.get("accepted") else "During page load"),
         "Lifetime": "Session" if c["session"] else "Persistent",
         "Secure": c["secure"], "HttpOnly": c["http_only"], "SameSite": c["same_site"]}
        for c in browser.get("cookies", [])
    ]), width="stretch", hide_index=True)
    st.caption("Cookie values are never read into reports or history.")


def _target_picker(browser: dict) -> str:
    targets = available_targets(browser)
    options = ["Type a value"] + [t["label"] for t in targets]
    choice = st.selectbox("What do you want to trace?", options,
                          help="A domain, script URL or any text, e.g. a tracking ID")
    if choice == "Type a value":
        return st.text_input("Domain, URL or text", placeholder="tracking.example.com")
    return next(t["value"] for t in targets if t["label"] == choice)


SCOPES = {
    "This page and what it uses": "page",
    "Whole repository (/content, /conf, /apps)": "repository",
}


def _analysis(result: dict, target: str, search_aem: bool, scope: str) -> dict:
    key = (result["timestamp"], target, search_aem, scope)
    cache = st.session_state["analysis_cache"]
    if key not in cache:
        cache[key] = analyze_target(result, target, session_tokens=st.session_state["session_aem_tokens"],
                                    ui_sessions=st.session_state["aem_ui_sessions"],
                                    search_aem=search_aem, scope=scope)
    return cache[key]


def _attribution_tab(analysis: dict, target: str) -> None:
    if not target.strip():
        st.info("Choose or type a target above.")
        return
    for finding in analysis["findings"]:
        with st.expander(f"{finding['source']} · {finding['confidence']} · {finding['requests']} request(s)",
                         expanded=True):
            st.write(finding["explanation"])
            st.caption(finding["method"])
            for evidence in finding["evidence"]:
                st.code(evidence, language=None)


def _groovy_hint(result: dict, target: str) -> None:
    """Point to the Groovy Runner when code under /apps wasn't found by search."""
    folders = aem_code_folders(result["browser"]["requests"]) or ["/apps/<your-project>"]
    st.info(
        "Nothing found under /apps? AEM's full-text search doesn't cover code files. "
        "In the **AEM Groovy Runner**, run **Find Text References** with:\n\n"
        f"- Paths: `{'`, `'.join(folders)}`\n- Text: `{target.strip()}`\n\n"
        "It reads clientlib JavaScript, HTL and CSS directly, read-only."
    )


MAX_AUTO_SCREENSHOTS = 6


def _properties_pages(result: dict, analysis: dict) -> list[str]:
    """The scanned page, then any page whose own properties matched the search."""
    pages = [t["path"] for t in _screenshot_targets(analysis) if t["kind"] == "page"]
    return list(dict.fromkeys([result["aem_page"]["content_path"]] + pages))


def _screenshot_targets(analysis: dict) -> list[dict]:
    """What to screenshot for each AEM match: Page Properties when the match is
    on a page's own node, else that component instance's edit dialog."""
    targets = {}
    for entry in analysis["aem_references"]:
        for hit in entry["hits"]:
            node, resource_type = hit["node_path"], hit["resource_type"]
            if node.endswith("/jcr:content"):
                targets.setdefault(("page", hit["page_path"]), {
                    "kind": "page", "path": hit["page_path"], "title": "Page Properties of " + hit["page_path"]})
            elif node.startswith("/content/") and resource_type and not resource_type.startswith("property "):
                targets.setdefault(("component", node), {
                    "kind": "component", "path": node, "resource_type": resource_type,
                    "title": f"{resource_type.rsplit('/', 1)[-1]} component at {node}"})
    return list(targets.values())


def _capture(result: dict, target_item: dict, term: str) -> dict:
    """One dialog capture as {"item", "result"}, {"item", "error"} or {"item", "sign_in"}.

    Taken in the signed-in AEM window when there is one (AEM's UI only trusts
    the browser the user signed in with); else in a new browser with a token."""
    environment = result["environment"]
    mock = aem_lookup.is_mock(environment)
    window = aem_browser.get_window(environment["id"])
    if mock and not window and sign_in_to_aem(environment):  # the sample sign-in needs no user action
        window = aem_browser.get_window(environment["id"])
    term = term.strip()
    try:
        if window and target_item["kind"] == "page":
            shot = aem_browser.capture_page_properties(window, target_item["path"], term)
        elif window:
            shot = aem_browser.capture_component_dialog(window, target_item["path"],
                                                        target_item["resource_type"], term)
        else:
            auth = environment_auth(environment, st.session_state["session_aem_tokens"])
            if auth["method"] != "token":
                return {"item": target_item, "sign_in": True,
                        "reason": "Screenshots are taken in the AEM window you sign in with, and it isn't open."}
            options = dict(show_browser=settings.show_browser)
            if target_item["kind"] == "page":
                shot = capture_page_properties(environment["author_base"], target_item["path"], term,
                                               auth["auth"], **options)
            else:
                shot = capture_component_dialog(environment["author_base"], target_item["path"],
                                                target_item["resource_type"], term, auth["auth"], **options)
        return {"item": target_item, "result": shot}
    except aem_browser.WindowClosed:
        return {"item": target_item, "sign_in": True,
                "reason": "The AEM window was closed, so screenshots need a new sign-in."}
    except AemLoginRequired as exc:
        if not exc.sign_in_page:
            return {"item": target_item, "error": {"title": "The dialog opened a different page", "reasons": [
                f"Landed on {exc.landed}" + (f" (“{exc.title}”)" if exc.title else ""),
                "Send this message to the developer to adjust the screenshot address.",
            ]}}
        if window:
            # Leave the window open: the sign-in page is in it, and can be finished there.
            return {"item": target_item, "sign_in": True, "in_window": True, "landed": exc.landed,
                    "blocked": exc.blocked,
                    "reason": "AEM showed a sign-in page in the AEM window instead of the dialog."}
        return {"item": target_item, "sign_in": True, "landed": exc.landed, "blocked": exc.blocked,
                "reason": "AEM showed a sign-in page instead of the dialog."}
    except Exception as exc:  # noqa: BLE001 - shown to the user as a friendly error
        error = friendly_error(exc)
        return {"item": target_item, "error": {"title": error.title, "reasons": error.reasons}}


def _capture_pages(result: dict, targets: list[dict], term: str, key: tuple) -> None:
    """Capture each target, stopping at the first sign-in request."""
    items = []
    with st.spinner("Taking screenshots on AEM author..."):
        for target_item in targets:
            item = _capture(result, target_item, term)
            items.append(item)
            if item.get("sign_in"):
                break
    st.session_state["properties_captures"] = {"key": key, "items": items, "targets": targets}


def auto_capture(result: dict, analysis: dict, target: str, key: tuple) -> None:
    """After Search AEM: screenshot the dialog behind each match."""
    targets = _screenshot_targets(analysis)[:MAX_AUTO_SCREENSHOTS]
    if targets:
        _capture_pages(result, targets, target, key)
    else:
        st.session_state["properties_captures"] = None


def _show_captures(captures: dict, target: str) -> None:
    for index, item in enumerate(captures["items"]):
        st.markdown(f"**{item['item']['title']}**")
        if item.get("error"):
            show_error({"title": "Screenshot failed: " + item["error"]["title"], "reasons": item["error"]["reasons"]})
            continue
        if item.get("sign_in"):
            continue
        shot = item["result"]
        status = shot.get("status") or 0
        st.markdown(f"[Open in AEM]({shot['url']}) · " + " · ".join(
            f"`{a['url'].split('/mnt/', 1)[-1][:90]}` → {a['status']}" for a in shot.get("attempts", [])))
        if status >= 400:
            st.caption(f"AEM answered {status} for every address tried. Use **Open in AEM** to check the "
                       "address in your own browser: if it fails there too, the address form doesn't suit this "
                       "AEM; if it works there, tell the developer.")
        elif not shot["fields"]:
            st.caption(f"No field in this dialog shows “{target}” (it may be in a field the dialog doesn't "
                       "display). The dialog as opened:")
        if not shot["fields"]:
            st.image(shot["page_image"], width="stretch")
        for number, field in enumerate(shot["fields"], 1):
            where = " › ".join(field.get("tabs") or [])
            if field.get("visible") is False:
                st.caption("The field's tab couldn't be opened, so it may not show in this screenshot.")
            st.image(field["image"], width="stretch",
                     caption=(f"Tab: {where} · " if where else "")
                     + f"{field['label'] or field['name']} = {field['value'][:120]}")
            st.download_button("Download screenshot", field["image"],
                               f"aem-{item['item']['path'].rsplit('/', 1)[-1]}-{number}.png", "image/png",
                               key=f"aem_screenshot_{index}_{number}")
        if shot["blocked_writes"]:
            st.caption(f"{len(shot['blocked_writes'])} write request(s) from the author UI were blocked.")


def _properties_screenshot(result: dict, analysis: dict, target: str, key: tuple) -> None:
    st.markdown("#### AEM screenshots")
    st.caption("For each match: Page Properties when the target is a page property, or that component's "
               "edit dialog when it's in a component, on the right tab with the field highlighted. "
               "Read-only: the browser blocks every write request and clicks only dialog tabs.")
    if not target.strip():
        st.info("Choose or type a target above.")
        return

    captures = st.session_state.get("properties_captures")
    current = captures if captures and captures["key"] == key else None

    if current and any(item.get("sign_in") for item in current["items"]):
        item = next(item for item in current["items"] if item.get("sign_in"))
        landed = f" It opened {item['landed']}." if item.get("landed") else ""
        if item.get("in_window"):
            st.warning(f"{item['reason']}{landed} If it asks you to sign in, finish that in the AEM window "
                       "(don't close it), then click **Search AEM** again.")
        else:
            st.warning(f"{item.get('reason', 'AEM needs a sign-in for screenshots.')}{landed} Use **Sign in to "
                       "AEM** at the top of the page and keep the AEM window open; the screenshots are taken "
                       "right after.")
        if item.get("blocked"):
            with st.expander(f"{len(item['blocked'])} write request(s) to AEM were blocked meanwhile"):
                st.code("\n".join(item["blocked"][:20]), language=None)
        if st.button("Retry screenshots", key="retry_screenshots"):
            _capture_pages(result, current["targets"], target, key)
            st.rerun()
        return

    if current:
        taken = sum(len(item["result"]["fields"]) for item in current["items"] if item.get("result"))
        if taken:
            st.success(f"{taken} screenshot(s) taken.")
        _show_captures(current, target)
    elif st.session_state.get("aem_searched") == key:
        st.caption("No match in AEM to screenshot.")

    with st.expander("Screenshot another page's properties"):
        page = st.selectbox("Page", _properties_pages(result, analysis), key="properties_page")
        if st.button("Screenshot Page Properties in AEM"):
            _capture_pages(result, [{"kind": "page", "path": page, "title": "Page Properties of " + page}],
                           target, key)
            st.rerun()


def _aem_tab(result: dict, analysis: dict, target: str, searched: bool, key: tuple) -> None:
    page = result.get("aem_page")
    stage = result["stages"].get("aem", {})
    if needs_sign_in(result):
        st.warning(f"{stage.get('detail', 'Not signed in to AEM')}. Use **Sign in to AEM** at the top of "
                   "the page; the AEM lookups then run for this scan.")
        return
    if not page:
        st.warning("AEM lookup unavailable: " + (stage.get("detail") or stage.get("status", "")))
        return
    if page["status"] == "found":
        st.success(f"AEM page: `{page['content_path']}` ({page.get('method', '')})")
        st.write({"Title": page.get("title"), "Template": page.get("template"),
                  "Page component": page.get("resource_type")})
    else:
        st.warning("Page not found in AEM: " + page.get("message", ""))

    st.markdown("#### Where AEM references the target")
    if not target.strip():
        st.info("Choose or type a target above.")
    elif not searched:
        st.info("Choose a scope and click “Search AEM” above.")
    else:
        for entry in analysis["aem_references"]:
            where = entry["scope"] if entry["scope"] == entry["root"] else f"{entry['scope']} · `{entry['root']}`"
            st.markdown(f"**{where}**: {entry['total']} hit(s)"
                        + ("" if entry["status"] != "error" else f", {entry['message']}"))
            if entry["hits"]:
                st.dataframe(pd.DataFrame([
                    {"Node": h["node_path"], "Page": h["page_path"], "Component": h["resource_type"]}
                    for h in entry["hits"]
                ]), width="stretch", hide_index=True)
        st.caption("A reference shows where the value is stored, not proof that it caused a request. "
                   "Full-text search depends on the AEM index; code in /apps may not be indexed.")
        code = [e for e in analysis["aem_references"] if e["root"] == "/apps" or e["scope"] == "Site code"]
        if not code or not any(e["hits"] for e in code):
            _groovy_hint(result, target)

    if page["status"] == "found" and searched:
        st.divider()
        _properties_screenshot(result, analysis, target, key)


def _report_tab(result: dict, browser: dict, analysis: dict, target: str) -> None:
    report = build_report(result, analysis["findings"], analysis["aem_references"], target)
    col1, col2, col3 = st.columns(3)
    col1.download_button("JSON report", json.dumps(report, indent=2, default=str),
                         "investigation.json", "application/json")
    col2.download_button("HTML report", html_report(report), "investigation.html", "text/html")
    col3.download_button("Requests (CSV)", requests_csv(browser["requests"]), "requests.csv", "text/csv")
    st.caption("Reports contain URLs and cookie names, never cookie values or AEM tokens. Review before sharing.")


def render() -> None:
    st.title("Inspect a page")
    mock = st.session_state["mock_mode"]
    mappings, _ = _configuration(mock)
    _run_form(mappings, mock)
    _aem_connection(mappings, _configuration(mock)[1], mock)

    result = st.session_state.get("result")
    if not result:
        st.info("Enter a website URL and run the investigation.")
        return

    st.dataframe(pd.DataFrame([
        {"Stage": stage_label(name), "Status": detail["status"], "Details": detail["detail"]}
        for name, detail in result["stages"].items()
    ]), width="stretch", hide_index=True)

    if result.get("browser_error"):
        show_error(result["browser_error"])
    browser = result.get("browser")
    if not browser:
        return

    _overview(result, browser)
    _changes(result)

    st.divider()
    st.header("Trace a script or domain")
    target = _target_picker(browser)
    page_found = (result.get("aem_page") or {}).get("status") == "found"
    col1, col2 = st.columns([3, 1])
    scope_label = col1.radio(
        "Search scope", list(SCOPES) if page_found else list(SCOPES)[1:], horizontal=True,
        help="This page: its components, the experience fragments it uses, its parent pages' "
             "properties, its template and site policies, and its code folder.",
    )
    scope = SCOPES[scope_label]
    searched = col2.button("Search AEM", type="primary",
                           disabled=not (target.strip() and page_found),
                           help="Read-only search on author for this target")
    if not page_found:
        col2.caption("Needs the AEM page: sign in to AEM at the top." if needs_sign_in(result)
                     else "Needs the AEM page, which wasn't found for this URL.")
    elif not target.strip():
        col2.caption("Choose what to trace first.")
    key = (result["timestamp"], target, scope)
    if searched:
        st.session_state["aem_searched"] = key
    search_aem = st.session_state.get("aem_searched") == key
    analysis = _analysis(result, target, search_aem, scope)
    if searched and page_found:
        auto_capture(result, analysis, target, key)

    # Results of the trace stay right here, not in a tab: tabs reset to the
    # first one whenever the page refreshes, which hid them.
    if target.strip():
        st.subheader("How it was added")
        _attribution_tab(analysis, target)
        st.subheader("In AEM")
        _aem_tab(result, analysis, target, search_aem, key)

    st.divider()
    st.header("Scan details")
    tabs = st.tabs(["Technologies", "Third parties", "Consent & cookies", "Dependency graph",
                    "Page screenshot", "Report"])
    with tabs[0]:
        _technologies_tab(result)
    with tabs[1]:
        _third_parties_tab(result, browser)
    with tabs[2]:
        _consent_tab(result, browser)
    with tabs[3]:
        edges = request_graph(browser)
        if edges:
            graph = dot_graph(edges)
            st.graphviz_chart(graph, width="stretch")
            st.download_button("Download graph (.dot)", graph, "dependencies.dot", "text/plain")
        else:
            st.info("No script-to-request relationships were captured.")
    with tabs[4]:
        if browser.get("screenshot"):
            st.image(browser["screenshot"], caption=browser.get("title", ""), width="stretch")
            st.download_button("Download screenshot", browser["screenshot"], "screenshot.png", "image/png")
        else:
            st.info("No screenshot (mock mode, or the scan did not complete).")
    with tabs[5]:
        _report_tab(result, browser, analysis, target)
