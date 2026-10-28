from __future__ import annotations

"""State, navigation, and small widgets shared across every page in
web_inspector/ui/*. Page-specific rendering stays in that page's own module."""

import streamlit as st

from .. import VERSION, aem_lookup, aem_mock
from ..aem_screens import SignInIncomplete, sign_in
from ..config import settings
from ..errors import FriendlyError, friendly_error

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
        # Session-only Basic-auth credentials for websites, keyed by domain.
        "session_site_credentials": {},
        # Author UI sign-ins for screenshots (browser cookies), keyed by environment id.
        # Memory only: they work like a password for the AEM account.
        "aem_ui_sessions": {},
        "properties_captures": None,
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


def signed_in(environment: dict) -> bool:
    return environment["id"] in st.session_state["aem_ui_sessions"]


def sign_in_to_aem(environment: dict) -> bool:
    """Open a browser on author, wait for the user to sign in, keep the session in memory."""
    mock = aem_lookup.is_mock(environment)
    with st.spinner("A browser window is open on AEM author: sign in there. It closes by itself."):
        try:
            state = sign_in(environment["author_base"], show_browser=not mock,
                            prepare_context=aem_mock.serve_author_ui if mock else None)
        except SignInIncomplete as exc:
            show_error({"title": "Not signed in", "reasons": [str(exc)]})
            return False
        except Exception as exc:  # noqa: BLE001 - shown to the user as a friendly error
            error = friendly_error(exc)
            show_error({"title": "Sign-in failed: " + error.title, "reasons": error.reasons})
            return False
    st.session_state["aem_ui_sessions"][environment["id"]] = state
    return True


def sign_out_of_aem(environment: dict) -> None:
    st.session_state["aem_ui_sessions"].pop(environment["id"], None)

