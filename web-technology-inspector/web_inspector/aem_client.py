"""Read-only AEM HTTP access.

All application AEM inspection requests must use this module.
"""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, unquote

import requests

ALLOWED_METHODS = frozenset({"GET", "HEAD"})

QUERYBUILDER_PATH = "/bin/querybuilder.json"

# Read-only QueryBuilder parameters the inspector may send.
QUERYBUILDER_PARAMETERS = frozenset({
    "path",
    "type",
    "property",
    "property.value",
    "property.operation",
    "fulltext",
    "p.limit",
    "p.hits",
    "p.properties",
})

# Repository roots a QueryBuilder search may cover.
QUERYBUILDER_ROOTS = ("/content", "/conf", "/apps")

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


def _unsafe_path(path):
    return (
        any(
            segment in (".", "..")
            for segment in path.split("/")
        )
        or "\\" in path
        or "//" in path
    )


def _validate_querybuilder(query):
    """Allow only read-only search parameters within approved roots."""

    parameters = parse_qsl(query, keep_blank_values=True)

    if not parameters:
        raise AEMSecurityError("QueryBuilder query is required")

    names = [name for name, _ in parameters]

    if len(names) != len(set(names)):
        raise AEMSecurityError(
            "Repeated QueryBuilder parameters are not permitted"
        )

    for name, value in parameters:
        if name not in QUERYBUILDER_PARAMETERS:
            raise AEMSecurityError(
                "QueryBuilder parameter is not permitted: " + name
            )

        # Only "exists": find nodes that have a property, e.g. fragment references.
        if name == "property.operation" and value != "exists":
            raise AEMSecurityError(
                "QueryBuilder property.operation may only be 'exists'"
            )

        if name == "p.limit" and not (
            value.isdigit() and 1 <= int(value) <= 100
        ):
            raise AEMSecurityError(
                "QueryBuilder p.limit must be between 1 and 100"
            )

    search_root = dict(parameters).get("path", "")

    if (
        not any(
            search_root == root
            or search_root.startswith(root + "/")
            for root in QUERYBUILDER_ROOTS
        )
        or _unsafe_path(search_root)
    ):
        raise AEMSecurityError(
            "QueryBuilder path must be under "
            + ", ".join(QUERYBUILDER_ROOTS)
        )


def validate_request(method, url, origins=None):
    """Validate method, destination, and content endpoint.

    Permitted endpoints:
    - /content/.../jcr:content.json, a single page node (no query)
    - /bin/querybuilder.json with an allowlisted, read-only query
    """

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

    if parsed.fragment:
        raise AEMSecurityError("Fragments are not permitted")

    if origins is None:
        origins = approved_origins()

    if (
        parsed.scheme,
        parsed.netloc.lower()
    ) not in origins:
        raise AEMSecurityError(
            "Destination is not an approved AEM Author origin"
        )

    path = unquote(parsed.path)

    if path == QUERYBUILDER_PATH:
        _validate_querybuilder(parsed.query)
        return method

    if parsed.query:
        raise AEMSecurityError(
            "Query parameters are only permitted for QueryBuilder"
        )

    if (
        not path.startswith("/content/")
        or not path.endswith("/jcr:content.json")
        or _unsafe_path(path)
    ):
        raise AEMSecurityError(
            "Only approved content JSON endpoints "
            "are permitted"
        )

    return method


def aem_request(method, url, auth, origins=None):
    """Execute an authorized read-only request.

    auth is either an AEM token (str, sent as a Bearer header) or
    {"cookies": {...}}: the login cookies of an author sign-in.
    """

    method = validate_request(method, url, origins)

    headers = {"Accept": "application/json"}
    cookies = None

    if isinstance(auth, str) and auth.strip():
        headers["Authorization"] = "Bearer " + auth.strip()
    elif isinstance(auth, dict) and auth.get("cookies"):
        cookies = dict(auth["cookies"])
    else:
        raise ValueError("AEM sign-in or token is required")

    response = requests.request(
        method,
        url,
        headers=headers,
        cookies=cookies,
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
