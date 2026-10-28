"""Read-only AEM lookups that tie a published page to repository content.

- verify_page: confirm that a mapped content path exists (one node, not a tree)
- find_vanity: find the page that owns a vanity URL when mapping misses
- search_references: find nodes under /content, /conf or /apps that mention a value

Every request goes through modules.aem, so the read-only and destination
rules apply. Set MOCK_AEM=true to answer from modules.aem_mock instead.
"""

import os
from urllib.parse import quote, urlencode, urlsplit

import requests

from modules import aem_mock
from modules.aem import (
    QUERYBUILDER_PATH,
    QUERYBUILDER_ROOTS,
    AEMSecurityError,
    aem_request,
    validate_request,
)

# What each HTTP status most likely means for these endpoints.
STATUS_MESSAGES = {
    401: "AEM rejected the token; it may have expired",
    403: "Your AEM user is not allowed to call this endpoint",
    404: "Not found",
}


def mock_enabled():
    return os.environ.get("MOCK_AEM", "").strip().lower() in ("1", "true", "yes")


def _origin(environment):
    parsed = urlsplit(environment["author_base"])
    return {(parsed.scheme, parsed.netloc.lower())}


def _get_json(environment, url, token):
    """Return (http_status, payload or None, message)."""

    if mock_enabled():
        # Validate exactly as a real request would be.
        validate_request("GET", url, _origin(environment))
        response = aem_mock.get(url)
        if response.status_code != 200:
            return response.status_code, None, STATUS_MESSAGES.get(
                response.status_code, "HTTP " + str(response.status_code)
            )
        return 200, response.json(), "OK"

    try:
        response = aem_request("GET", url, token, _origin(environment))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        return status, None, STATUS_MESSAGES.get(status, "HTTP " + str(status))
    except AEMSecurityError as exc:
        return 0, None, "Blocked: " + str(exc)
    except requests.RequestException as exc:
        return 0, None, "Connection failed: " + type(exc).__name__

    try:
        return response.status_code, response.json(), "OK"
    except ValueError:
        return response.status_code, None, "AEM returned a non-JSON response"


def page_node_url(environment, content_path):
    return (
        environment["author_base"].rstrip("/")
        + quote(content_path, safe="/")
        + "/jcr:content.json"
    )


def querybuilder_url(environment, parameters):
    return (
        environment["author_base"].rstrip("/")
        + QUERYBUILDER_PATH
        + "?"
        + urlencode(parameters)
    )


def verify_page(environment, content_path, token):
    """Confirm the page exists by reading only its jcr:content node."""

    status, node, message = _get_json(
        environment, page_node_url(environment, content_path), token
    )

    if node is None:
        return {
            "status": "not_found" if status == 404 else "error",
            "content_path": content_path,
            "http_status": status,
            "message": message,
        }

    return {
        "status": "found",
        "content_path": content_path,
        "http_status": status,
        "message": message,
        "title": node.get("jcr:title", ""),
        "template": node.get("cq:template", ""),
        "resource_type": node.get("sling:resourceType", ""),
    }


def _hit_paths(payload):
    return [
        hit.get("jcr:path", "")
        for hit in payload.get("hits", [])
        if hit.get("jcr:path")
    ]


def _page_path(node_path):
    return node_path.split("/jcr:content", 1)[0]


def find_vanity(environment, published_path, token, root="/content"):
    """Find pages whose sling:vanityPath matches the published path."""

    vanity = published_path.rstrip("/") or "/"
    if vanity.endswith(".html"):
        vanity = vanity[: -len(".html")]

    status, payload, message = _get_json(
        environment,
        querybuilder_url(environment, [
            ("path", root),
            ("property", "sling:vanityPath"),
            ("property.value", vanity),
            ("p.limit", "10"),
            ("p.hits", "selective"),
            ("p.properties", "jcr:path"),
        ]),
        token,
    )

    if payload is None:
        return {"status": "error", "vanity": vanity, "http_status": status,
                "message": message, "pages": []}

    pages = list(dict.fromkeys(_page_path(p) for p in _hit_paths(payload)))
    return {
        "status": "found" if pages else "not_found",
        "vanity": vanity,
        "http_status": status,
        "message": message,
        "pages": pages,
    }


def search_references(environment, term, token, roots=QUERYBUILDER_ROOTS, limit=20):
    """Full-text search each root for nodes that mention the term."""

    results = []

    for root in roots:
        status, payload, message = _get_json(
            environment,
            querybuilder_url(environment, [
                ("path", root),
                # Quoted, so a domain or URL is searched as one phrase.
                ("fulltext", '"' + term.replace('"', "") + '"'),
                ("p.limit", str(limit)),
                ("p.hits", "selective"),
                ("p.properties", "jcr:path sling:resourceType"),
            ]),
            token,
        )

        if payload is None:
            results.append({"root": root, "status": "error", "http_status": status,
                            "message": message, "total": 0, "hits": []})
            continue

        hits = [
            {
                "node_path": hit.get("jcr:path", ""),
                "page_path": _page_path(hit.get("jcr:path", "")),
                "resource_type": hit.get("sling:resourceType", ""),
            }
            for hit in payload.get("hits", [])
            if hit.get("jcr:path")
        ]
        results.append({
            "root": root,
            "status": "found" if hits else "not_found",
            "http_status": status,
            "message": message,
            "total": payload.get("total", len(hits)),
            "hits": hits,
        })

    return results
