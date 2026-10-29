from __future__ import annotations

"""State, navigation, and small widgets shared across every page in
web_inspector/ui/*. Page-specific rendering stays in that page's own module."""

import re
from pathlib import Path

import streamlit as st

from .. import VERSION, aem_browser, aem_lookup, aem_mock, preferences
from ..aem_screens import SignInIncomplete
from ..config import settings
from ..errors import FriendlyError, friendly_error

PAGE_NAMES = ["Inspect", "History", "Settings"]

CUSTOM_CSS = """<style>
.block-container{max-width:1450px;padding-top:1.35rem}
[data-testid=stMetric]{border:1px solid #ddd;padding:1rem;border-radius:14px}
</style>"""


def init_session_state() -> None:
    defaults = {
        # Last choice made in the sidebar, else MOCK_MODE from .env.
        "mock_mode": preferences.get("mock_mode", settings.mock_mode),
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
            preferences.set("mock_mode", mock)
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


def block_saving() -> bool:
    """Whether the AEM window blocks saving (off by default: it's the user's own login)."""
    return bool(preferences.get("aem_block_saving", False))


def remember_sign_in() -> bool:
    return bool(preferences.get("aem_remember_sign_in", True))


def aem_profile_dir(environment: dict) -> Path:
    """The AEM window's saved browser profile for an environment (git-ignored data folder)."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", environment["id"])
    return settings.data_path / "aem-browser" / safe


def sign_in_to_aem(environment: dict) -> bool:
    """Open an AEM window, wait for the user to sign in, and keep it open for screenshots.

    Its login cookies are also kept in memory for the AEM lookups. With
    "remember" on, the window's profile is saved, so a later sign-in goes
    through by itself while AEM still accepts it."""
    mock = aem_lookup.is_mock(environment)
    remember = remember_sign_in() and not mock
    message = ("Signing in to AEM with your saved login; if AEM asks, sign in in the AEM window."
               if remember and aem_profile_dir(environment).exists() else
               "An AEM window is open: sign in there. Keep it open (it's used for screenshots).")
    with st.spinner(message):
        try:
            window = aem_browser.open_window(environment["id"], environment["author_base"],
                                             show_browser=not mock,
                                             prepare_context=aem_mock.serve_author_ui if mock else None,
                                             block_saving=block_saving(),
                                             profile_dir=aem_profile_dir(environment) if remember else None,
                                             use_chrome=not mock)
            state = window.storage_state
        except SignInIncomplete as exc:
            show_error({"title": "Not signed in", "reasons": [str(exc)]})
            return False
        except Exception as exc:  # noqa: BLE001 - shown to the user as a friendly error
            error = friendly_error(exc)
            show_error({"title": "Sign-in failed: " + error.title, "reasons": error.reasons})
            return False
    st.session_state["aem_ui_sessions"][environment["id"]] = state
    return True


def forget_aem_sign_in(environment: dict) -> None:
    """Sign out and delete the saved login for the environment."""
    st.session_state["aem_ui_sessions"].pop(environment["id"], None)
    aem_browser.forget_sign_in(environment["id"], aem_profile_dir(environment))


def sign_out_of_aem(environment: dict) -> None:
    st.session_state["aem_ui_sessions"].pop(environment["id"], None)
    aem_browser.close_window(environment["id"])

