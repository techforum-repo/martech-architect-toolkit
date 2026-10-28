"""Basic-authentication credentials for non-production websites.

Kept per published domain, either in the browser session only or encrypted
on this machine through token_store (key in the OS credential store), never
in the website mappings file, scan history, reports or logs.
"""

from __future__ import annotations

import json

from . import token_store


def _store_key(domain: str) -> dict:
    # token_store keys secrets by an environment's id and base URL.
    domain = domain.lower()
    return {"id": "basic-auth|" + domain, "author_base": "https://" + domain}


def valid(username: str, password: str) -> bool:
    # A colon would split differently when the browser builds the Basic header.
    return bool(username.strip()) and bool(password) and ":" not in username


def save(domain: str, username: str, password: str) -> None:
    if not valid(username, password):
        raise ValueError("Enter a username (without ':') and a password")
    token_store.save_token(_store_key(domain), json.dumps({"username": username.strip(), "password": password}))


def load(domain: str) -> dict | None:
    """Stored {"username", "password"} for the domain, or None."""
    stored = token_store.get_token(_store_key(domain))
    if not stored:
        return None
    value = json.loads(stored)
    return {"username": value["username"], "password": value["password"]}


def delete(domain: str) -> None:
    token_store.delete_token(_store_key(domain))


def resolve(domain: str, session_credentials: dict | None) -> tuple[dict | None, str]:
    """(credentials, where they came from) for a domain: session first, then saved."""
    domain = domain.lower()
    if session_credentials and domain in session_credentials:
        return session_credentials[domain], "session"
    try:
        saved = load(domain)
    except Exception:  # noqa: BLE001 - an unavailable keyring means "none saved" here
        return None, ""
    return (saved, "saved") if saved else (None, "")


def browser_credentials(url_host: str, credentials: dict | None) -> dict | None:
    """Playwright http_credentials, answered only to the site itself.

    The browser sends them when the site challenges with HTTP 401; "origin"
    keeps them away from every third-party request the page makes.
    """
    if not credentials:
        return None
    return {
        "username": credentials["username"],
        "password": credentials["password"],
        "origin": "https://" + url_host.lower(),
    }
