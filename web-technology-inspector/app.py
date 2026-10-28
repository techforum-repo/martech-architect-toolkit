from __future__ import annotations

import streamlit as st

from web_inspector import database
from web_inspector.config import harden_env_file
from web_inspector.ui import history_page, inspect_page, settings_page
from web_inspector.ui.shared import CUSTOM_CSS, init_session_state, render_sidebar

harden_env_file()
database.initialize()
st.set_page_config(page_title="Web Technology Inspector", page_icon="🔎", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

init_session_state()
page = render_sidebar()

PAGES = {
    "Inspect": inspect_page.render,
    "History": history_page.render,
    "Settings": settings_page.render,
}
PAGES[page]()
