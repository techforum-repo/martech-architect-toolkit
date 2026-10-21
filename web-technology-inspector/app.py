from modules.target_selector import available_targets
"""Web Technology Inspector v0.9."""

import json
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from modules.config_manager import load, match
from modules.scan_orchestrator import (
    run_investigation,
    analyze_target,
    safe_report,
)
from modules.advanced import (
    request_graph,
    dot_graph,
    html_report,
    validate_public_url,
)
from modules.page_visual import capture_screenshot

st.set_page_config(
    page_title="Web Technology Inspector",
    layout="wide"
)

st.title("Web Technology Inspector")
st.caption(
    "One scan. Technology discovery, AEM evidence, "
    "dependency analysis and consolidated reporting."
)

mappings = load(
    "aem_mappings.json", "mappings"
)

environments = load(
    "aem_environments.json", "environments"
)

with st.sidebar:
    st.header("Investigation")
    st.caption("AEM configuration is available under Settings.")

url = st.text_input(
    "Website URL",
    placeholder="https://www.example.com/en/page.html"
)

target = st.text_input(
    "Investigate domain, script or property (optional)",
    placeholder="tracking.example.com"
)

mapping = match(url, mappings) if url else None

if mapping:
    st.success("Mapped website: " + mapping["name"])
elif url:
    st.warning("No website mapping found.")

# =========================================
# RUN COMPLETE SCAN
# =========================================

if st.button(
    "Run Complete Investigation",
    type="primary",
    disabled=not bool(mapping)
):
    with st.spinner("Running consolidated investigation..."):
        investigation = run_investigation(
            url,
            mappings,
            environments,
            session_tokens=st.session_state.get(
                "session_aem_tokens", {}
            )
        )

    st.session_state["v09_result"] = investigation
    st.session_state.pop("v09_screenshot", None)

    st.toast("Investigation completed")

saved = st.session_state.get("v09_result")

result = (
    saved
    if saved and saved["url"] == url
    else None
)

if result is None:
    st.info(
        "Enter an authorized website URL and run "
        "the complete investigation."
    )
    st.stop()

# =========================================
# SCAN STATUS
# =========================================

st.subheader("Investigation Status")

status_rows = [
    {
        "Stage": name,
        "Status": detail["status"],
        "Details": detail["detail"],
    }
    for name, detail in result["stages"].items()
]

st.dataframe(
    pd.DataFrame(status_rows),
    width="stretch",
    hide_index=True
)

browser = result.get("browser") or {}
requests = browser.get("requests", [])

# Select a detected resource or use a custom search value.
targets = available_targets(browser)

if targets:
    labels = ["Custom search"] + [
        item["label"] for item in targets
    ]

    selection = st.selectbox(
        "Select a detected technology resource",
        labels,
        key="detected_target_selection"
    )

    if selection != "Custom search":
        selected = next(
            item["value"]
            for item in targets
            if item["label"] == selection
        )
        target = selected

    st.caption(
        "Selection filters attribution and AEM evidence "
        "without repeating the browser scan."
    )

analysis = analyze_target(result, target)

# =========================================
# OVERVIEW
# =========================================

st.header("Overview")

c1, c2, c3, c4 = st.columns(4)

c1.metric("Requests", len(requests))
c2.metric("Scripts", len(browser.get("scripts", [])))
c3.metric("Technologies", len(result["technologies"]))

third_party = {
    r.get("domain")
    for r in requests
    if r.get("domain")
    and r.get("domain") != urlsplit(url).hostname
}

c4.metric("Third-party domains", len(third_party))

# =========================================
# CONSOLIDATED RESULTS
# =========================================

tabs = st.tabs([
    "Technologies",
    "How It Was Added",
    "AEM Evidence",
    "Dependency Graph",
    "Visual Evidence",
    "Report",
])

with tabs[0]:
    st.subheader("Technology Inventory")

    technologies = result["technologies"]

    if technologies:
        rows = [
            {
                "Technology": t["technology"],
                "Detection": t["classification"],
                "Evidence Count": len(t["evidence"]),
            }
            for t in technologies
        ]
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True
        )
    else:
        st.info("No recognized technology signatures detected.")

    with st.expander("All Network Requests"):
        if requests:
            rows = []
            for r in requests:
                rows.append({
                    "Domain": str(r.get("domain") or ""),
                    "URL": str(r.get("url") or ""),
                    "Type": str(r.get("type") or ""),
                    "Status": str(r.get("status") or ""),
                    "Initiator": str(
                        r.get("initiator_url") or ""
                    ),
                })
            st.dataframe(
                pd.DataFrame(rows),
                width="stretch"
            )

with tabs[1]:
    st.subheader("How Was This Added?")

    if not target.strip():
        st.info(
            "Enter a domain or script identifier "
            "above to investigate its source."
        )
    else:
        for finding in analysis["findings"]:
            with st.expander(
                finding["source"]
                + " - "
                + finding["confidence"],
                expanded=True
            ):
                st.write(finding["explanation"])
                st.write("**Method:**", finding["method"])

                for evidence in finding["evidence"]:
                    st.code(str(evidence))

        if not analysis["findings"]:
            st.info("No browser attribution evidence available.")

with tabs[2]:
    st.subheader("AEM Authored Content")

    st.write(
        "**Resolved content path:**",
        result.get("content_path") or "Unavailable"
    )

    if result.get("aem") is not None:
        from modules.page_investigator import page_summary

        with st.expander("Page Metadata"):
            st.json(page_summary(result["aem"]))

        matches = analysis["properties"]

        if matches:
            st.dataframe(
                pd.DataFrame(matches),
                width="stretch"
            )
        elif target.strip():
            st.info(
                "No matching property found in retrieved content."
            )
        else:
            st.info(
                "Enter a search value to inspect "
                "matching authored properties."
            )
    else:
        st.warning(
            "AEM content was not available for this scan."
        )

with tabs[3]:
    st.subheader("Script Dependency Graph")

    edges = request_graph(browser)

    if edges:
        graph = dot_graph(edges)
        st.graphviz_chart(graph, width="stretch")

        st.download_button(
            "Download Graph",
            graph,
            "dependencies.dot",
            "text/plain"
        )
    else:
        st.info("No dependency relationships captured.")

with tabs[4]:
    st.subheader("Published Page Screenshot")

    if st.button("Capture Screenshot"):
        try:
            approved = {
                m["published_domain"].lower()
                for m in mappings
            }

            validate_public_url(url, approved)

            screenshot = capture_screenshot(
                url,
                mapping["published_domain"]
            )

            st.session_state["v09_screenshot"] = {
                "url": url,
                "data": screenshot,
            }

        except Exception as exc:
            st.error(
                "Screenshot failed: "
                + type(exc).__name__
            )

    screenshot = st.session_state.get("v09_screenshot")

    if screenshot and screenshot["url"] == url:
        image = screenshot["data"]["image"]

        st.image(image, width="stretch")

        st.download_button(
            "Download Screenshot",
            image,
            "screenshot.png",
            "image/png"
        )

with tabs[5]:
    st.subheader("Consolidated Report")

    report = safe_report(result, analysis)

    st.download_button(
        "Download JSON Report",
        json.dumps(report, indent=2, default=str),
        "investigation.json",
        "application/json"
    )

    st.download_button(
        "Download HTML Report",
        html_report(report),
        "investigation.html",
        "text/html"
    )

    st.caption(
        "Reports may contain sensitive URLs or property "
        "values. Review before sharing."
    )

st.divider()
st.caption(
    "Web Technology Inspector v0.9 | "
    "Read-only AEM access | "
    "No tag-management API integration"
)


