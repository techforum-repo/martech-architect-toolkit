from __future__ import annotations

"""State, navigation, and small widgets shared across every page in
web_inspector/ui/*. Page-specific rendering stays in that page's own module."""

import streamlit as st

from .. import VERSION
from ..config import settings
from ..errors import FriendlyError

PAGE_NAMES = ["Inspect", "History", "Settings"]

CUSTOM_CSS = """<style>
.block-container{max-width:1450px;padding-top:1.35rem}
[data-testid=stMetric]{border:1px solid #ddd;padding:1rem;border-radius:14px}
</style>"""


def init_session_state() -> None:
    defaults = {
        "mock_mode": settings.mock_mode,
        # Session-only AEM tokens, keyed by "<environment id>|<author URL>".
        "session_aem_tokens": {},
        "result": None,
        "analysis_cache": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar() -> str:
    with st.sidebar:
        st.header("Web Technology Inspector")
        page = st.radio("Page", PAGE_NAMES, label_visibility="collapsed")
        st.divider()
        mock = st.toggle(
            "Mock mode",
            value=st.session_state["mock_mode"],
            help="Sample scan and sample AEM data. Nothing is loaded from the web or AEM.",
        )
        if mock != st.session_state["mock_mode"]:
            st.session_state["mock_mode"] = mock
            st.session_state["result"] = None
            st.session_state["analysis_cache"] = {}
        if mock:
            st.caption("Using sample data. Turn off to scan real websites.")
        st.caption(f"v{VERSION} · read-only AEM access")
    return page


def show_error(error: FriendlyError | dict) -> None:
    title = error.title if isinstance(error, FriendlyError) else error["title"]
    reasons = error.reasons if isinstance(error, FriendlyError) else error["reasons"]
    st.error(title)
    if reasons:
        st.markdown("\n".join(f"- {reason}" for reason in reasons))


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:.2f} MB"
