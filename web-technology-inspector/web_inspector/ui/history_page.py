"""Past scans, and what changed between any two scans of a page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import database


def _label(scan: dict) -> str:
    when = scan["scanned_at"][:16].replace("T", " ")
    return f"#{scan['id']} · {when} UTC · {scan['device']}" + (" · mock" if scan["mock"] else "")


def render() -> None:
    st.title("History")
    scans = database.list_scans()
    if not scans:
        st.info("No scans yet. Run one on the Inspect page.")
        return

    st.dataframe(pd.DataFrame([
        {"#": s["id"], "Scanned (UTC)": s["scanned_at"][:16].replace("T", " "), "URL": s["url"],
         "Device": s["device"], "Consent": s["consent"], "Mock": s["mock"],
         "Technologies": len(s["summary"]["technologies"]),
         "Third parties before consent": len(s["summary"]["before_consent_domains"])}
        for s in scans
    ]), width="stretch", hide_index=True)

    st.subheader("Compare two scans of a page")
    url = st.selectbox("Page", sorted({s["url"] for s in scans}))
    page_scans = [s for s in scans if s["url"] == url]
    if len(page_scans) < 2:
        st.info("This page has only one scan. Scan it again to compare.")
        return

    col1, col2 = st.columns(2)
    newer = col1.selectbox("Newer scan", page_scans, format_func=_label)
    older = col2.selectbox("Older scan", [s for s in page_scans if s["id"] != newer["id"]], format_func=_label)
    if older["device"] != newer["device"] or older["mock"] != newer["mock"]:
        st.warning("These scans used a different device or mode, so some differences are expected.")

    diff = database.compare(older["summary"], newer["summary"])
    if not any(v["added"] or v["removed"] for v in diff.values()):
        st.success("No differences in technologies, domains, cookies or before-consent requests.")
        return
    for key, value in diff.items():
        if value["added"] or value["removed"]:
            st.markdown(f"**{key.replace('_', ' ').capitalize()}**")
            st.markdown("\n".join([f"- ➕ {x}" for x in value["added"]] + [f"- ➖ {x}" for x in value["removed"]]))
