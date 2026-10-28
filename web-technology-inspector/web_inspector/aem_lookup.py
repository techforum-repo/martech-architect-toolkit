"""Read-only AEM lookups that tie a published page to repository content.

- verify_page: confirm that a mapped content path exists (one node, not a tree)
- find_vanity: find the page that owns a vanity URL when mapping misses
- search_references: find nodes under /content, /conf or /apps that mention a value

Every request goes through aem_client, so the read-only and destination
rules apply. The sample environment in aem_mock is answered from sample
data instead, after the same validation.
"""

from urllib.parse import quote, urlencode, urlsplit

import requests

from . import aem_mock
from .aem_client import (
    QUERYBUILDER_PATH,
    QUERYBUILDER_ROOTS,
    AEMSecurityError,
    aem_request,
    validate_request,
)

# What each HTTP status most likely means for these endpoints.
STATUS_MESSAGES = {
    401: "AEM rejected the sign-in or token; it may have expired. Sign in again",
    403: "Your AEM user is not allowed to call this endpoint",
    404: "Not found",
}


def is_mock(environment):
    return environment.get("id") == aem_mock.ENVIRONMENT["id"]


def _origin(environment):
    parsed = urlsplit(environment["author_base"])
    return {(parsed.scheme, parsed.netloc.lower())}


# Shown when AEM answers with a redirect, which for these JSON endpoints
# means its sign-in page: the session has ended.
SIGN_IN_AGAIN = "AEM sent the request to its sign-in page; the sign-in has expired. Sign in again"


def session_auth(environment, storage_state):
    """Auth for aem_request from an author sign-in: its cookies for the author host only."""
    host = urlsplit(environment["author_base"]).hostname or ""
    cookies = {
        c["name"]: c["value"]
        for c in (storage_state or {}).get("cookies", [])
        if host == c["domain"].lstrip(".") or host.endswith("." + c["domain"].lstrip("."))
    }
    return {"cookies": cookies} if cookies else None


def _get_json(environment, url, auth):
    """Return (http_status, payload or None, message). auth: see aem_client.aem_request."""

    if is_mock(environment):
        # Validate exactly as a real request would be.
        validate_request("GET", url, _origin(environment))
        response = aem_mock.get(url)
        if response.status_code != 200:
            return response.status_code, None, STATUS_MESSAGES.get(
                response.status_code, "HTTP " + str(response.status_code)
            )
        return 200, response.json(), "OK"

    try:
        response = aem_request("GET", url, auth, _origin(environment))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        return status, None, STATUS_MESSAGES.get(status, "HTTP " + str(status))
    except AEMSecurityError as exc:
        if "redirects" in str(exc):
            return 302, None, SIGN_IN_AGAIN
        return 0, None, "Blocked: " + str(exc)
    except requests.RequestException as exc:
        return 0, None, "Connection failed: " + type(exc).__name__
    except ValueError:
        return 0, None, "Not signed in to AEM"

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


def verify_page(environment, content_path, auth):
    """Confirm the page exists by reading only its jcr:content node."""

    status, node, message = _get_json(
        environment, page_node_url(environment, content_path), auth
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


def find_vanity(environment, published_path, auth, root="/content"):
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
        auth,
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


def _fulltext(environment, root, term, auth, limit=20, scope=""):
    """One QueryBuilder full-text search under root, as a result entry."""
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
        auth,
    )
    entry = {"scope": scope or root, "root": root, "http_status": status, "message": message}

    if payload is None:
        return dict(entry, status="error", total=0, hits=[])

    hits = [
        {
            "node_path": hit.get("jcr:path", ""),
            "page_path": _page_path(hit.get("jcr:path", "")),
            "resource_type": hit.get("sling:resourceType", ""),
        }
        for hit in payload.get("hits", [])
        if hit.get("jcr:path")
    ]
    return dict(entry, status="found" if hits else "not_found",
                total=payload.get("total", len(hits)), hits=hits)


def search_references(environment, term, auth, roots=QUERYBUILDER_ROOTS, limit=20):
    """Full-text search each whole root (/content, /conf, /apps) for the term."""
    return [_fulltext(environment, root, term, auth, limit) for root in roots]


MAX_FRAGMENTS = 10
MAX_ANCESTORS = 8


def fragments_used(environment, page_path, auth):
    """Experience fragment variations the page references."""
    status, payload, _ = _get_json(
        environment,
        querybuilder_url(environment, [
            ("path", page_path + "/jcr:content"),
            ("property", "fragmentVariationPath"),
            ("property.operation", "exists"),
            ("p.limit", "50"),
            ("p.hits", "selective"),
            ("p.properties", "fragmentVariationPath"),
        ]),
        auth,
    )
    if payload is None:
        return []
    paths = [
        hit.get("fragmentVariationPath", "")
        for hit in payload.get("hits", [])
    ]
    return list(dict.fromkeys(
        p for p in paths if isinstance(p, str) and p.startswith("/content/")
    ))[:MAX_FRAGMENTS]


def _ancestors(page_path):
    """Parent pages from the site root down, e.g. /content/site, /content/site/us."""
    parts = page_path.strip("/").split("/")
    return ["/" + "/".join(parts[:depth]) for depth in range(2, len(parts))][-MAX_ANCESTORS:]


def inherited_properties(environment, page_path, term, auth):
    """Parent pages' own properties that mention the term (one node read each)."""
    lowered = term.lower()
    hits = []
    for ancestor in _ancestors(page_path):
        status, node, _ = _get_json(environment, page_node_url(environment, ancestor), auth)
        if node is None:
            continue  # not a page, or not readable
        for name, value in node.items():
            values = value if isinstance(value, list) else [value]
            if any(isinstance(v, str) and lowered in v.lower() for v in values):
                hits.append({
                    "node_path": ancestor + "/jcr:content",
                    "page_path": ancestor,
                    "resource_type": "property " + name,
                })
    return {
        "scope": "Inherited from parent pages", "root": "parent pages", "http_status": 200,
        "message": "OK", "status": "found" if hits else "not_found", "total": len(hits), "hits": hits,
    }


def _site_conf(template):
    """/conf/<site> from a template path like /conf/<site>/settings/wcm/templates/x."""
    if template.startswith("/conf/") and "/settings/" in template:
        return template.split("/settings/", 1)[0]
    return None


def search_page_scope(environment, page, term, auth, code_folders=()):
    """Search only the page and the shared things it uses.

    page: verify_page() result for the page (content_path, template).
    code_folders: /apps/<project> folders from the page's clientlib URLs.
    """
    page_path = page["content_path"]
    results = [_fulltext(environment, page_path + "/jcr:content", term, auth, scope="This page")]

    for fragment in fragments_used(environment, page_path, auth):
        results.append(_fulltext(environment, fragment, term, auth, scope="Experience fragment"))

    results.append(inherited_properties(environment, page_path, term, auth))

    template = page.get("template") or ""
    if template.startswith("/conf/"):
        results.append(_fulltext(environment, template, term, auth, scope="Page template"))
        site_conf = _site_conf(template)
        if site_conf:
            results.append(_fulltext(environment, site_conf + "/settings/wcm/policies", term, auth,
                                     scope="Site policies"))

    for folder in code_folders:
        results.append(_fulltext(environment, folder, term, auth, scope="Site code"))

    return results
