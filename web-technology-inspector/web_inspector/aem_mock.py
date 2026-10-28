"""Sample AEM responses for running lookups without an AEM environment.

Used for the sample ENVIRONMENT below (mock mode). Requests are still
validated by aem_client, so mock mode exercises the same security rules.
"""

from urllib.parse import parse_qsl, urlsplit, unquote

ENVIRONMENT = {
    "id": "env_mock",
    "name": "Mock Author",
    "author_base": "https://author-p00000-e000000.adobeaemcloud.com",
}

MAPPING = {
    "name": "Mock website",
    "published_domain": "www.example.com",
    "published_prefix": "/us/en",
    "content_root": "/content/example/us/en",
    "environment_id": ENVIRONMENT["id"],
}

PAGES = {
    "/content/example/us/en": {
        "jcr:title": "Home",
        # Inherited by child pages, e.g. read by the page component.
        "analyticsTrackingDomain": "tracking.example.com",
        "cq:template": "/conf/example/settings/wcm/templates/page-content",
        "sling:resourceType": "example/components/page",
    },
    "/content/example/us/en/products": {
        "jcr:title": "Products",
        "cq:template": "/conf/example/settings/wcm/templates/page-content",
        "sling:resourceType": "example/components/page",
    },
    "/content/example/us/en/campaigns/spring-sale": {
        "jcr:title": "Spring Sale",
        "cq:template": "/conf/example/settings/wcm/templates/landing-page",
        "sling:resourceType": "example/components/page",
        "sling:vanityPath": ["/spring"],
    },
}

# Experience fragment variations each page references (fragmentVariationPath).
FRAGMENTS = {
    "/content/example/us/en/products": [
        "/content/experience-fragments/example/us/en/site/footer/master",
    ],
}

# Nodes whose properties mention a searchable value.
REFERENCES = {
    "tracking.example.com": [
        (
            "/content/example/us/en/products/jcr:content/root/container/embed",
            "core/wcm/components/embed/v2/embed",
        ),
        (
            "/content/experience-fragments/example/us/en/site/footer/master"
            "/jcr:content/root/html",
            "example/components/html",
        ),
        # On another page: found by the whole-repository search, not the page scope.
        (
            "/content/example/us/en/campaigns/spring-sale/jcr:content/root/embed",
            "core/wcm/components/embed/v2/embed",
        ),
        (
            "/conf/example/settings/wcm/policies/example/components/page"
            "/policy_analytics",
            "wcm/core/components/policy/policy",
        ),
    ],
}


class MockResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _querybuilder(parameters):
    root = parameters.get("path", "")
    limit = int(parameters.get("p.limit", "20"))

    if parameters.get("property") == "fragmentVariationPath":
        page = root[: -len("/jcr:content")] if root.endswith("/jcr:content") else root
        hits = [
            {"jcr:path": page + "/jcr:content/root/xf", "fragmentVariationPath": fragment}
            for fragment in FRAGMENTS.get(page, [])
        ]
        return {"success": True, "results": len(hits), "total": len(hits), "more": False, "hits": hits}

    if parameters.get("property") == "sling:vanityPath":
        wanted = parameters.get("property.value", "")
        paths = [
            path + "/jcr:content"
            for path, node in PAGES.items()
            if path.startswith(root) and wanted in node.get("sling:vanityPath", [])
        ]
    else:
        term = parameters.get("fulltext", "").strip('"').lower()
        paths = [
            path
            for value, nodes in REFERENCES.items()
            if term and term in value.lower()
            for path, _ in nodes
            if path.startswith(root + "/")
        ]

    resource_types = {
        path: resource_type
        for nodes in REFERENCES.values()
        for path, resource_type in nodes
    }
    hits = [
        {"jcr:path": path, "sling:resourceType": resource_types.get(path, "")}
        for path in paths[:limit]
    ]
    return {
        "success": True,
        "results": len(hits),
        "total": len(paths),
        "more": len(paths) > limit,
        "hits": hits,
    }


def get(url):
    """Answer a validated GET request from the sample data."""

    parsed = urlsplit(url)
    path = unquote(parsed.path)

    if path == "/bin/querybuilder.json":
        return MockResponse(200, _querybuilder(dict(parse_qsl(parsed.query))))

    if path.endswith("/jcr:content.json"):
        page = path[: -len("/jcr:content.json")]
        if page in PAGES:
            return MockResponse(200, PAGES[page])
        return MockResponse(404, {})

    return MockResponse(404, {})


def _dialog(page_path):
    """A small Page Properties dialog in AEM's markup for a sample page."""
    from html import escape

    props = PAGES.get(page_path, {})
    basic = {"jcr:title": props.get("jcr:title", "")}
    advanced = {k: v for k, v in props.items() if k not in basic and isinstance(v, str)}

    def fields(values):
        return "".join(
            f"<div class='coral-Form-fieldwrapper' style='margin:12px 0'><label style='display:block;font:13px sans-serif;"
            f"color:#555'>{escape(k)}</label><input name='./{escape(k)}' value='{escape(v)}' "
            f"style='width:640px;padding:6px;font:14px sans-serif'></div>"
            for k, v in values.items()
        )

    return (
        "<!doctype html><html><head><title>Page Properties (sample)</title></head>"
        "<body style='font:14px sans-serif;margin:24px'>"
        f"<h2 style='margin:0 0 12px'>Page Properties: {escape(page_path)} (sample)</h2>"
        "<coral-tablist style='display:flex;gap:16px;border-bottom:1px solid #ccc;padding-bottom:6px'>"
        "<coral-tab onclick='show(0)' style='cursor:pointer'>Basic</coral-tab>"
        "<coral-tab onclick='show(1)' style='cursor:pointer'>Advanced</coral-tab></coral-tablist>"
        f"<coral-panelstack><coral-panel>{fields(basic)}</coral-panel>"
        f"<coral-panel style='display:none'>{fields(advanced)}</coral-panel></coral-panelstack>"
        "<script>function show(i){document.querySelectorAll('coral-panel')"
        ".forEach((p,n)=>p.style.display=n===i?'':'none')}"
        # Like an author that only accepts its own login session for UI pages.
        "if(!document.cookie.includes('login-token'))location.href='https://ims.example.test/ims/login'"
        "</script></body></html>"
    )


def serve_author_ui(context):
    """Playwright route handler serving the sample author UI (mock mode)."""
    def handle(route):
        url = urlsplit(route.request.url)
        if url.path == "/aem/start.html":
            # Sample sign-in: author sets its login cookie straight away.
            route.fulfill(status=200, content_type="text/html", body="<title>AEM Start (sample)</title>",
                          headers={"Set-Cookie": "login-token=sample; Path=/; Secure"})
        elif url.path == "/mnt/overlay/wcm/core/content/sites/properties.html":
            route.fulfill(status=200, content_type="text/html",
                          body=_dialog(dict(parse_qsl(url.query)).get("item", "")))
        elif url.hostname == "ims.example.test":
            route.fulfill(status=200, content_type="text/html", body="<title>Sign in (sample)</title>")
        else:
            route.fulfill(status=200, body=b"")

    context.route("**/*", handle)

