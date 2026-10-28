"""Manage reusable AEM environments and website mappings."""

import uuid

import pandas as pd
import streamlit as st

from ..config import settings
from ..site_config import load, save, valid_author
from ..token_store import (
    token_status,
    save_token,
    delete_token,
)


def render():
    st.title("Settings")

    st.caption(
        f"Mode: {'mock (sample data)' if st.session_state.get('mock_mode') else 'live'}"
        f" · Scan timeout {settings.scan_timeout}s · Settle {settings.settle_seconds}s"
        " · Change defaults in .env"
    )

    envs = load("aem_environments.json", "environments")
    mappings = load("aem_mappings.json", "mappings")

    tab1, tab2 = st.tabs([
        "AEM Environments",
        "Website Mappings"
    ])

    with tab1:
        st.subheader("AEM Environments")

        if envs:
            st.dataframe(
                pd.DataFrame(envs),
                width="stretch"
            )

        with st.form("new_environment"):
            name = st.text_input("Environment Name")
            author = st.text_input(
                "Author Base URL",
                placeholder="https://author.example.com"
            )
            create = st.form_submit_button("Add Environment")

        if create:
            if not name.strip() or not valid_author(author):
                st.error("Enter a name and valid HTTPS Author URL.")
            elif any(
                e["author_base"] == author.rstrip("/")
                for e in envs
            ):
                st.error("Environment already exists.")
            else:
                envs.append({
                    "id": "env_" + uuid.uuid4().hex[:12],
                    "name": name.strip(),
                    "author_base": author.rstrip("/")
                })
                save("aem_environments.json", "environments", envs)
                st.rerun()

        if envs:
            st.divider()
            index = st.selectbox(
                "Manage Environment",
                range(len(envs)),
                format_func=lambda i: envs[i]["name"]
            )

            env = envs[index]
            identity = (
                env["id"]
                + "|"
                + env["author_base"].rstrip("/")
            )

            session_token = st.session_state.get(
                "session_aem_tokens", {}
            ).get(identity)

            auth = token_status(
                env,
                session_token=session_token
            )

            st.info(auth["message"])

            with st.form("edit_environment"):
                edit_name = st.text_input(
                    "Name", value=env["name"]
                )
                edit_author = st.text_input(
                    "Author URL", value=env["author_base"]
                )
                update = st.form_submit_button(
                    "Save Environment"
                )

            if update:
                if not edit_name.strip() or not valid_author(edit_author):
                    st.error("Invalid environment details.")
                elif any(
                    i != index and
                    e["author_base"] == edit_author.rstrip("/")
                    for i, e in enumerate(envs)
                ):
                    st.error("Author URL already configured.")
                else:
                    env.update(
                        name=edit_name.strip(),
                        author_base=edit_author.rstrip("/")
                    )
                    save("aem_environments.json", "environments", envs)
                    st.rerun()

            st.subheader("AEM Developer Console Authentication")

            st.caption(
                "Supports long AEM Developer Console tokens. "
                "Persistent tokens are encrypted locally, with "
                "the encryption key stored in the OS credential vault."
            )

            storage_mode = st.radio(
                "Token storage",
                ["Encrypted local storage", "Session only"],
                horizontal=True,
                key="aem_storage_mode"
            )

            with st.form("environment_token"):
                token = st.text_area(
                    "AEM Developer Console Access Token",
                    height=120,
                    placeholder="Paste your access token",
                    help="Token contents are never displayed in reports."
                )
                store = st.form_submit_button(
                    "Save / Replace Token"
                )

            if store:
                try:
                    if not token.strip():
                        st.error("Enter an access token.")
                    elif storage_mode == "Session only":
                        if "session_aem_tokens" not in st.session_state:
                            st.session_state["session_aem_tokens"] = {}

                        identity = (
                            env["id"]
                            + "|"
                            + env["author_base"].rstrip("/")
                        )

                        st.session_state["session_aem_tokens"][identity] = token.strip()

                        st.toast("Session token configured")
                        st.rerun()
                    else:
                        save_token(env, token)
                        st.toast("Encrypted token saved")
                        st.rerun()
                except Exception as exc:
                    st.error(
                        "Credential storage failed: "
                        + type(exc).__name__
                    )

            identity = (
                env["id"]
                + "|"
                + env["author_base"].rstrip("/")
            )

            if st.button("Clear Session Token"):
                st.session_state.get(
                    "session_aem_tokens", {}
                ).pop(identity, None)
                st.rerun()

            if st.button("Remove Token"):
                try:
                    delete_token(env)
                    st.rerun()
                except Exception as exc:
                    st.error(type(exc).__name__)

            if st.button("Delete Environment"):
                if any(
                    m["environment_id"] == env["id"]
                    for m in mappings
                ):
                    st.error(
                        "Remove associated website mappings first."
                    )
                elif auth["status"] not in ("missing", "unavailable"):
                    st.error("Remove the stored token first.")
                else:
                    envs.pop(index)
                    save("aem_environments.json", "environments", envs)
                    st.rerun()


    with tab2:
        st.subheader("Website Mappings")

        def mapping_valid(name, domain, prefix, root):
            from urllib.parse import urlsplit

            domain = domain.strip().lower()
            prefix = prefix.rstrip("/") or "/"
            root = root.rstrip("/")

            try:
                parsed = urlsplit("https://" + domain)

                return (
                    bool(name.strip())
                    and bool(domain)
                    and parsed.hostname == domain
                    and parsed.port is None
                    and not parsed.username
                    and not parsed.password
                    and prefix.startswith("/")
                    and root.startswith("/content/")
                    and all(
                        part not in (".", "..")
                        for part in prefix.split("/")
                    )
                    and all(
                        part not in (".", "..")
                        for part in root.split("/")
                    )
                )
            except ValueError:
                return False

        if not envs:
            st.warning("Create an AEM environment first.")

        else:
            options = {
                e["id"]: e["name"]
                for e in envs
            }

            if "mapping_mode" not in st.session_state:
                st.session_state.mapping_mode = "list"

            # ---------------------------------
            # Header
            # ---------------------------------

            col1, col2 = st.columns([4, 1])

            with col1:
                st.caption(
                    "Manage published website URLs and "
                    "their corresponding AEM content roots."
                )

            with col2:
                if st.button(
                    "+ New Mapping",
                    type="primary",
                    width="stretch"
                ):
                    st.session_state.mapping_mode = "new"
                    st.rerun()

            # ---------------------------------
            # Existing mappings
            # ---------------------------------

            if mappings:
                rows = []

                for index, item in enumerate(mappings):
                    rows.append({
                        "Name": item["name"],
                        "Domain": item["published_domain"],
                        "Prefix": item["published_prefix"],
                        "Content Root": item["content_root"],
                        "Environment": options.get(
                            item["environment_id"],
                            "Unknown"
                        )
                    })

                st.dataframe(
                    pd.DataFrame(rows),
                    width="stretch",
                    hide_index=True
                )

            else:
                st.info("No website mappings configured.")

            # ---------------------------------
            # New mapping
            # ---------------------------------

            if st.session_state.mapping_mode == "new":

                st.divider()
                st.subheader("Add Website Mapping")

                with st.form("new_mapping_v104"):

                    name = st.text_input(
                        "Website Name",
                        placeholder="Example Website"
                    )

                    domain = st.text_input(
                        "Published Domain",
                        placeholder="www.example.com"
                    )

                    prefix = st.text_input(
                        "Published URL Prefix",
                        value="/en"
                    )

                    root = st.text_input(
                        "AEM Content Root",
                        placeholder="/content/example/en"
                    )

                    eid = st.selectbox(
                        "AEM Environment",
                        list(options),
                        format_func=lambda x: options[x]
                    )

                    save_new = st.form_submit_button(
                        "Save New Mapping",
                        type="primary"
                    )

                if save_new:
                    domain = domain.strip().lower()
                    prefix = prefix.rstrip("/") or "/"
                    root = root.rstrip("/")

                    duplicate = any(
                        m["published_domain"].lower() == domain
                        and m["published_prefix"] == prefix
                        for m in mappings
                    )

                    if not mapping_valid(
                        name, domain, prefix, root
                    ):
                        st.error("Please enter valid mapping details.")

                    elif duplicate:
                        st.error(
                            "A mapping already exists for "
                            "this domain and prefix."
                        )

                    else:
                        mappings.append({
                            "name": name.strip(),
                            "published_domain": domain,
                            "published_prefix": prefix,
                            "content_root": root,
                            "environment_id": eid
                        })

                        save(
                            "aem_mappings.json",
                            "mappings",
                            mappings
                        )

                        st.session_state.mapping_mode = "list"
                        st.toast("Website mapping created")
                        st.rerun()

                if st.button("Cancel New Mapping"):
                    st.session_state.mapping_mode = "list"
                    st.rerun()

            # ---------------------------------
            # Edit existing mapping
            # ---------------------------------

            elif mappings:

                st.divider()
                st.subheader("Edit Existing Mapping")

                selected_index = st.selectbox(
                    "Select Website Mapping",
                    range(len(mappings)),
                    format_func=lambda i: (
                        mappings[i]["name"]
                        + " | "
                        + mappings[i]["published_domain"]
                        + mappings[i]["published_prefix"]
                    ),
                    key="mapping_selection_v104"
                )

                current = mappings[selected_index]

                # Each selection receives a distinct
                # form identity, preventing stale values.
                form_id = (
                    "edit_mapping_v104_"
                    + str(selected_index)
                )

                with st.form(form_id):

                    edit_name = st.text_input(
                        "Website Name",
                        value=current["name"]
                    )

                    edit_domain = st.text_input(
                        "Published Domain",
                        value=current["published_domain"]
                    )

                    edit_prefix = st.text_input(
                        "Published URL Prefix",
                        value=current["published_prefix"]
                    )

                    edit_root = st.text_input(
                        "AEM Content Root",
                        value=current["content_root"]
                    )

                    environment_ids = list(options)

                    current_env = current["environment_id"]

                    env_index = (
                        environment_ids.index(current_env)
                        if current_env in environment_ids
                        else 0
                    )

                    edit_env = st.selectbox(
                        "AEM Environment",
                        environment_ids,
                        index=env_index,
                        format_func=lambda x: options[x]
                    )

                    save_edit = st.form_submit_button(
                        "Save Changes",
                        type="primary"
                    )

                if save_edit:

                    edit_domain = edit_domain.strip().lower()
                    edit_prefix = edit_prefix.rstrip("/") or "/"
                    edit_root = edit_root.rstrip("/")

                    duplicate = any(
                        i != selected_index
                        and item["published_domain"].lower()
                            == edit_domain
                        and item["published_prefix"]
                            == edit_prefix
                        for i, item in enumerate(mappings)
                    )

                    if not mapping_valid(
                        edit_name,
                        edit_domain,
                        edit_prefix,
                        edit_root
                    ):
                        st.error("Invalid mapping details.")

                    elif duplicate:
                        st.error(
                            "Another mapping already uses "
                            "this domain and prefix."
                        )

                    else:
                        mappings[selected_index] = {
                            "name": edit_name.strip(),
                            "published_domain": edit_domain,
                            "published_prefix": edit_prefix,
                            "content_root": edit_root,
                            "environment_id": edit_env
                        }

                        save(
                            "aem_mappings.json",
                            "mappings",
                            mappings
                        )

                        st.toast("Website mapping updated")
                        st.rerun()

                # ---------------------------------
                # Delete with confirmation
                # ---------------------------------

                with st.expander("Delete Mapping"):

                    st.warning(
                        "Deleting this mapping will remove "
                        "the website-to-AEM association."
                    )

                    confirm = st.checkbox(
                        "I confirm that I want to delete "
                        "this mapping",
                        key=(
                            "delete_confirm_v104_"
                            + str(selected_index)
                        )
                    )

                    if st.button(
                        "Delete Selected Mapping",
                        disabled=not confirm
                    ):
                        mappings.pop(selected_index)

                        save(
                            "aem_mappings.json",
                            "mappings",
                            mappings
                        )

                        st.session_state.pop(
                            "mapping_selection_v104",
                            None
                        )

                        st.toast("Website mapping deleted")
                        st.rerun()
