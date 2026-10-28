"""Inspect one page: scan it, then explore technologies, third parties,
consent, attribution and AEM evidence."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import aem_mock, database, mock_scan
from ..config import settings
from ..detection import EXPECTED_BEFORE_CONSENT, aem_code_folders, consent_violations
from ..investigation import analyze_target, run_investigation
from ..report import build_report, dot_graph, html_report, request_graph, requests_csv, stage_label
from ..site_config import load, match
from ..targets import available_targets
from .shared import megabytes, show_error

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

    if st.button("Run investigation", type="primary", disabled=not (url and known_domain)):
        with st.spinner("Scanning the page" + (" (a browser window will open)" if show_browser else "") + "..."):
            result = run_investigation(
                url, *_configuration(mock), mock=mock, device=device, consent=consent,
                show_browser=show_browser, timeout=settings.scan_timeout,
                settle=settings.settle_seconds, session_tokens=st.session_state["session_aem_tokens"],
            )
        result["consent_mode"] = consent
        if result.get("browser"):
            result["scan_id"] = database.save_scan(result, consent)
        st.session_state["result"] = result
        st.session_state["analysis_cache"] = {}


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


def _analysis(result: dict, target: str, search_aem: bool) -> dict:
    key = (result["timestamp"], target, search_aem)
    cache = st.session_state["analysis_cache"]
    if key not in cache:
        cache[key] = analyze_target(result, target, session_tokens=st.session_state["session_aem_tokens"],
                                    search_aem=search_aem)
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


def _aem_tab(result: dict, analysis: dict, target: str, searched: bool) -> None:
    page = result.get("aem_page")
    stage = result["stages"].get("aem", {})
    if not page:
        st.warning("AEM lookup unavailable: " + (stage.get("detail") or stage.get("status", "")))
        return
    if page["status"] == "found":
        st.success(f"AEM page: `{page['content_path']}` ({page.get('method', '')})")
        st.write({"Title": page.get("title"), "Template": page.get("template"),
                  "Page component": page.get("resource_type")})
    else:
        st.warning("Page not found in AEM: " + page.get("message", ""))

    st.subheader("Where AEM references the target")
    if not target.strip():
        st.info("Choose or type a target above.")
    elif not searched:
        st.info("Click “Search AEM” above to look for the target under /content, /conf and /apps.")
    else:
        for root in analysis["aem_references"]:
            st.markdown(f"**{root['root']}**: {root['total']} hit(s)"
                        + ("" if root["status"] != "error" else f", {root['message']}"))
            if root["hits"]:
                st.dataframe(pd.DataFrame([
                    {"Node": h["node_path"], "Page": h["page_path"], "Component": h["resource_type"]}
                    for h in root["hits"]
                ]), width="stretch", hide_index=True)
        st.caption("A reference shows where the value is stored, not proof that it caused a request. "
                   "Full-text search depends on the AEM index; code in /apps may not be indexed.")
        apps = next((r for r in analysis["aem_references"] if r["root"] == "/apps"), None)
        if apps and not apps["hits"]:
            _groovy_hint(result, target)


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
    target = _target_picker(browser)
    searched = st.button("Search AEM", disabled=not (target.strip() and result.get("aem_page")),
                         help="Search /content, /conf and /apps on author for this target")
    if searched:
        st.session_state["aem_searched"] = (result["timestamp"], target)
    search_aem = st.session_state.get("aem_searched") == (result["timestamp"], target)
    analysis = _analysis(result, target, search_aem)

    tabs = st.tabs(["Technologies", "Third parties", "Consent & cookies", "How it was added",
                    "AEM", "Dependency graph", "Screenshot", "Report"])
    with tabs[0]:
        _technologies_tab(result)
    with tabs[1]:
        _third_parties_tab(result, browser)
    with tabs[2]:
        _consent_tab(result, browser)
    with tabs[3]:
        _attribution_tab(analysis, target)
    with tabs[4]:
        _aem_tab(result, analysis, target, search_aem)
    with tabs[5]:
        edges = request_graph(browser)
        if edges:
            graph = dot_graph(edges)
            st.graphviz_chart(graph, width="stretch")
            st.download_button("Download graph (.dot)", graph, "dependencies.dot", "text/plain")
        else:
            st.info("No script-to-request relationships were captured.")
    with tabs[6]:
        if browser.get("screenshot"):
            st.image(browser["screenshot"], caption=browser.get("title", ""), width="stretch")
            st.download_button("Download screenshot", browser["screenshot"], "screenshot.png", "image/png")
        else:
            st.info("No screenshot (mock mode, or the scan did not complete).")
    with tabs[7]:
        _report_tab(result, browser, analysis, target)
