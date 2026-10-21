"""Read-only AEM HTTP access.

All application AEM inspection requests must use this module.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit, unquote

import requests

ALLOWED_METHODS = frozenset({"GET", "HEAD"})

CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "aem_environments.json"
)


class AEMSecurityError(PermissionError):
    """Raised when an AEM request violates security policy."""


def approved_origins():
    """Load approved Author origins from local configuration."""

    data = json.loads(
        CONFIG_PATH.read_text(encoding="utf-8-sig")
    )

    origins = set()

    for environment in data.get("environments", []):
        raw = environment.get("author_base", "")
        parsed = urlsplit(raw)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            continue

        origins.add(
            (parsed.scheme, parsed.netloc.lower())
        )

    return origins


def validate_request(method, url):
    """Validate method, destination, and content endpoint."""

    method = method.upper()

    if method not in ALLOWED_METHODS:
        raise AEMSecurityError(
            f"HTTP {method} is blocked. "
            "AEM integration is strictly read-only."
        )

    parsed = urlsplit(url)

    if parsed.scheme != "https":
        raise AEMSecurityError("HTTPS is required")

    if parsed.username or parsed.password:
        raise AEMSecurityError(
            "URL credentials are not permitted"
        )

    if parsed.query or parsed.fragment:
        raise AEMSecurityError(
            "Query parameters and fragments are not permitted"
        )

    if (
        parsed.scheme,
        parsed.netloc.lower()
    ) not in approved_origins():
        raise AEMSecurityError(
            "Destination is not an approved AEM Author origin"
        )

    path = unquote(parsed.path)

    if (
        not path.startswith("/content/")
        or not path.endswith(".infinity.json")
        or any(
            segment in (".", "..")
            for segment in path.split("/")
        )
        or "\\" in path
        or "//" in path
    ):
        raise AEMSecurityError(
            "Only approved content JSON endpoints "
            "are permitted"
        )

    return method


def aem_request(method, url, token):
    """Execute an authorized read-only request."""

    method = validate_request(method, url)

    if not isinstance(token, str) or not token.strip():
        raise ValueError("AEM bearer token is required")

    headers = {
        "Authorization": "Bearer " + token.strip(),
        "Accept": "application/json"
    }

    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=20,
        allow_redirects=False
    )

    # Never follow redirects with AEM credentials.
    if 300 <= response.status_code < 400:
        raise AEMSecurityError(
            "AEM redirects are blocked"
        )

    response.raise_for_status()

    return response


def inspect_page(url, token):
    """Retrieve AEM content without modifying it."""

    response = aem_request("GET", url, token)
    return response.json()


def find_references(data):
    """Find potentially relevant authored properties."""

    results = []

    keywords = (
        "script", "tag", "analytics", "tracking",
        "iframe", "embed", "clientlib", "src", "url"
    )

    def walk(node, path="", depth=0):
        if depth > 15 or len(results) >= 250:
            return

        if isinstance(node, dict):
            for key, value in node.items():
                current = path + "/" + key

                if isinstance(value, (str, int, float)):
                    if any(k in key.lower() for k in keywords):
                        results.append({
                            "property": current,
                            "value": str(value)[:400]
                        })
                else:
                    walk(value, current, depth + 1)

        elif isinstance(node, list):
            for index, value in enumerate(node[:100]):
                walk(
                    value,
                    path + "/" + str(index),
                    depth + 1
                )

    walk(data)
    return results
