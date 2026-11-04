"""Technology detection from observed requests, script URLs and page globals.

Signatures match a request's host or a URL pattern, never a bare substring,
so "chat.js" is not mistaken for Adobe Target's "at.js". A page global (for
example window.alloy) is the strongest evidence: the library actually ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Technology:
    name: str
    category: str
    hosts: tuple[str, ...] = ()    # regexes matched against the request hostname
    urls: tuple[str, ...] = ()     # regexes matched against the full URL
    globals: tuple[str, ...] = ()  # dotted names looked up on window
    tag_manager: bool = False


TECHNOLOGIES = (
    Technology("Adobe Experience Platform Web SDK", "Analytics & personalization",
               hosts=(r"(^|\.)adobedc\.net$",),
               # Also Edge Network calls through a first-party domain (edge.example.com/ee/...).
               urls=(r"/alloy(\.min)?\.js(\?|$)", r"/ee/([\w-]+/)?v\d+/(interact|collect)\?"),
               globals=("alloy", "__alloyNS")),
    Technology("Adobe Analytics", "Analytics",
               hosts=(r"\.sc\.omtrdc\.net$", r"(^|\.)2o7\.net$"),
               urls=(r"/AppMeasurement(\.min)?\.js(\?|$)", r"/b/ss/"), globals=("s_c_il",)),
    Technology("Adobe Target", "Personalization",
               hosts=(r"\.tt\.omtrdc\.net$",), urls=(r"/at(\.min)?\.js(\?|$)",),
               globals=("adobe.target",)),
    Technology("Adobe Experience Cloud ID", "Identity",
               urls=(r"/VisitorAPI(\.min)?\.js(\?|$)",), hosts=(r"^dpm\.demdex\.net$",),
               globals=("Visitor",)),
    Technology("Adobe Audience Manager", "Audience",
               hosts=(r"(^|\.)demdex\.net$",), globals=("DIL",)),
    Technology("Adobe Tags", "Tag management",
               hosts=(r"^assets\.adobedtm\.com$",), globals=("_satellite",), tag_manager=True),
    Technology("Adobe Client Data Layer", "Data layer",
               urls=(r"/adobe-client-data-layer[^/]*\.js",), globals=("adobeDataLayer",)),
    Technology("Google Tag Manager", "Tag management",
               urls=(r"googletagmanager\.com/gtm\.js",), globals=("google_tag_manager",),
               tag_manager=True),
    Technology("Google Analytics 4", "Analytics",
               urls=(r"googletagmanager\.com/gtag/js", r"(google-analytics|analytics\.google)\.com/g/collect"),
               globals=("gtag",)),
    Technology("Google Ads / Floodlight", "Advertising",
               hosts=(r"(^|\.)doubleclick\.net$", r"(^|\.)googleadservices\.com$")),
    Technology("Tealium iQ", "Tag management",
               hosts=(r"^tags\.tiqcdn\.com$",), urls=(r"/utag(\.\w+)?\.js(\?|$)",),
               globals=("utag",), tag_manager=True),
    Technology("Ensighten", "Tag management",
               hosts=(r"(^|\.)ensighten\.com$",), globals=("Bootstrapper",), tag_manager=True),
    Technology("OneTrust", "Consent management",
               hosts=(r"(^|\.)cookielaw\.org$", r"(^|\.)onetrust\.com$"), globals=("OneTrust",)),
    Technology("Cookiebot", "Consent management",
               hosts=(r"(^|\.)cookiebot\.com$",), globals=("Cookiebot",)),
    Technology("TrustArc", "Consent management",
               hosts=(r"(^|\.)trustarc\.com$",), globals=("truste",)),
    Technology("Sourcepoint", "Consent management",
               hosts=(r"(^|\.)sourcepoint\.(com|mgr\.consensu\.org)$", r"(^|\.)privacy-mgmt\.com$"),
               globals=("_sp_",)),
    Technology("IAB TCF consent API", "Consent management", globals=("__tcfapi",)),
    Technology("Meta Pixel", "Advertising",
               urls=(r"connect\.facebook\.net/.+/fbevents\.js",), globals=("fbq",)),
    Technology("LinkedIn Insight Tag", "Advertising",
               hosts=(r"^snap\.licdn\.com$", r"^px\.ads\.linkedin\.com$"),
               globals=("_linkedin_partner_id",)),
    Technology("Microsoft Clarity", "Session analytics",
               hosts=(r"(^|\.)clarity\.ms$",), globals=("clarity",)),
    Technology("Hotjar", "Session analytics",
               hosts=(r"(^|\.)hotjar\.com$",), globals=("hj",)),
    Technology("Contentsquare", "Session analytics",
               hosts=(r"(^|\.)contentsquare\.net$",), globals=("_uxa",)),
    Technology("Dynatrace", "Performance monitoring",
               urls=(r"/ruxitagentjs_",), globals=("dtrum",)),
    Technology("New Relic", "Performance monitoring",
               hosts=(r"(^|\.)nr-data\.net$",), globals=("NREUM",)),
    Technology("Cloudflare Web Analytics", "Analytics",
               hosts=(r"^static\.cloudflareinsights\.com$",)),
)

GLOBAL_NAMES = frozenset(name for tech in TECHNOLOGIES for name in tech.globals)

# Categories that have to load before consent to show the banner or apply it.
EXPECTED_BEFORE_CONSENT = frozenset({"Consent management", "Tag management"})


def _matches(tech: Technology, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(re.search(p, host) for p in tech.hosts) or any(
        re.search(p, url, re.IGNORECASE) for p in tech.urls
    )


_custom_cache: tuple[tuple | None, tuple[Technology, ...]] = (None, ())


def custom_technologies() -> tuple[Technology, ...]:
    """Technologies labelled in the app (custom_signatures), as host signatures."""
    global _custom_cache
    from . import custom_signatures  # late: it imports config, which tests patch
    stamp = custom_signatures.version()
    if stamp != _custom_cache[0]:
        _custom_cache = (stamp, tuple(
            Technology(entry["name"], entry["category"], hosts=(r"(^|\.)" + re.escape(entry["domain"]) + "$",))
            for entry in custom_signatures.load()
        ))
    return _custom_cache[1]


def technology_for_url(url: str, *, tag_managers_only: bool = False,
                       builtin_only: bool = False) -> Technology | None:
    """The first technology whose host or URL signature matches; built-in
    signatures first, then the ones labelled in the app."""
    for tech in TECHNOLOGIES + (() if builtin_only or tag_managers_only else custom_technologies()):
        if tag_managers_only and not tech.tag_manager:
            continue
        if _matches(tech, url):
            return tech
    return None


# --- What loaded a request ------------------------------------------------------

PAGE_HTML = "Page HTML"


def loaded_by(request: dict) -> str:
    """What made the browser send a request: a tag manager anywhere in its
    initiator chain, else the page's HTML, else the script that asked for it."""
    chain = [u for u in [request.get("initiator_url", "")] + list(request.get("stack_urls") or []) if u]
    for url in chain:
        manager = technology_for_url(url, tag_managers_only=True)
        if manager:
            return manager.name
    if request.get("initiator_type") == "parser":
        return PAGE_HTML
    if chain:
        parsed = urlparse(chain[0])
        return "Script " + (parsed.hostname or "") + "/…/" + parsed.path.rsplit("/", 1)[-1]
    return ""


def _loaders(tech_name: str, requests: list[dict]) -> list[str]:
    """Most common loaders first; a tag manager's own files loading each
    other isn't news, so its own name counts only when nothing else does."""
    counts: dict[str, int] = {}
    for request in requests:
        label = loaded_by(request)
        if label:
            counts[label] = counts.get(label, 0) + 1
    others = {k: v for k, v in counts.items() if k != tech_name} or counts
    return [label for label, _ in sorted(others.items(), key=lambda item: (-item[1], item[0]))][:3]


# --- Configuration IDs and versions ---------------------------------------------

# Page values read after the scan (scanner.DETAILS_SCRIPT): dotted path on
# window -> (technology, what it is). Scalars only, cut to 200 characters.
DETAIL_GLOBALS = {
    "_satellite.property.name": ("Adobe Tags", "Property"),
    "_satellite.environment.stage": ("Adobe Tags", "Environment"),
    "_satellite.buildInfo.buildDate": ("Adobe Tags", "Build date"),
    "adobe.target.VERSION": ("Adobe Target", "at.js version"),
    "Visitor.version": ("Adobe Experience Cloud ID", "VisitorAPI version"),
    "s_c_il.version": ("Adobe Analytics", "AppMeasurement version"),
}

# From request URLs: (technology, what it is, regex with the value in group 1).
DETAIL_URLS = (
    ("Adobe Experience Platform Web SDK", "Datastream ID", r"/ee/(?:[\w-]+/)?v\d+/(?:interact|collect)\?(?:.*&)?configId=([\w:-]+)"),
    ("Adobe Analytics", "Report suite", r"/b/ss/([^/?]+)/"),
    ("Adobe Target", "Client code", r"^https?://([a-z0-9-]+)\.tt\.omtrdc\.net/"),
    ("Adobe Tags", "Library environment", r"assets\.adobedtm\.com/.*/launch-[0-9a-f]+(-staging|-development)?(?:\.min)?\.js"),
    ("Google Tag Manager", "Container", r"googletagmanager\.com/gtm\.js\?(?:.*&)?id=(GTM-[A-Z0-9]+)"),
    ("Google Analytics 4", "Measurement ID", r"[?&](?:id|tid)=(G-[A-Z0-9]+)"),
    ("Meta Pixel", "Pixel ID", r"facebook\.com/tr/?\?(?:.*&)?id=(\d+)"),
)


def technology_details(requests: list[dict], scripts: list[str], page_details: dict | None) -> dict[str, list[str]]:
    """{technology: ["Report suite: abc", ...]}: IDs and versions that say
    which account, property or library version the page uses."""
    found: dict[str, dict[str, list[str]]] = {}

    def add(tech: str, what: str, value: str) -> None:
        values = found.setdefault(tech, {}).setdefault(what, [])
        if value and value not in values:
            values.append(value)

    for url in dict.fromkeys([r.get("url", "") for r in requests] + list(scripts)):
        for tech, what, pattern in DETAIL_URLS:
            match = re.search(pattern, url or "", re.IGNORECASE)
            if not match:
                continue
            if what == "Report suite":
                for suite in match.group(1).split(","):
                    add(tech, what, suite)
            elif what == "Library environment":
                add(tech, what, (match.group(1) or "-production").lstrip("-").title())
            else:
                add(tech, what, match.group(1))
    for path, value in (page_details or {}).items():
        if path in DETAIL_GLOBALS and isinstance(value, (str, int, float)) and str(value).strip():
            tech, what = DETAIL_GLOBALS[path]
            add(tech, what, str(value).strip()[:200])

    return {
        tech: [f"{what}: {', '.join(values[:5])}" + (f" (+{len(values) - 5})" if len(values) > 5 else "")
               for what, values in items.items() if values]
        for tech, items in found.items()
    }


def detect_technologies(requests: list[dict], scripts: list[str], page_globals: list[str],
                        page_details: dict | None = None) -> list[dict]:
    """One row per detected technology, with the evidence that matched, what
    loaded it, and the IDs and versions found for it."""
    resources = list(dict.fromkeys([r.get("url", "") for r in requests] + list(scripts)))
    present = set(page_globals or [])
    details = technology_details(requests, scripts, page_details)
    results = []

    for tech in TECHNOLOGIES + custom_technologies():
        custom = tech not in TECHNOLOGIES
        global_hits = [name for name in tech.globals if name in present]
        # A labelled domain only counts where no built-in signature matches.
        url_hits = [url for url in resources if url and _matches(tech, url)
                    and not (custom and technology_for_url(url, builtin_only=True))]
        if not global_hits and not url_hits:
            continue
        hit_set = set(url_hits)
        results.append({
            "technology": tech.name,
            "category": tech.category,
            # A global means the library executed; a request alone means it was fetched.
            "confidence": ("Labelled by you (loaded)" if custom
                           else "Confirmed (ran on the page)" if global_hits else "Observed (loaded)"),
            "evidence": [f"window.{name}" for name in global_hits] + url_hits[:20],
            "loaded_by": _loaders(tech.name, [r for r in requests if r.get("url") in hit_set]),
            "details": details.get(tech.name, []),
        })

    return results


def unidentified_third_parties(domains: list[dict]) -> list[dict]:
    """Third-party domains no signature (built-in or labelled) matched."""
    return [d for d in domains if not d["first_party"] and not d.get("technology")]


CLIENTLIB_PROJECT = re.compile(r"/etc\.clientlibs/([A-Za-z0-9_.-]+)/")


def aem_code_folders(requests: list[dict]) -> list[str]:
    """/apps folders the page's clientlibs come from: AEM serves /apps/<project>
    clientlibs at /etc.clientlibs/<project>/..., so the URLs name the folder."""
    projects = {
        match.group(1)
        for request in requests
        for match in [CLIENTLIB_PROJECT.search(request.get("url", ""))]
        if match and match.group(1) not in ("core", "clientlibs", "foundation", "granite", "cq", "wcm")
    }
    return sorted("/apps/" + project for project in projects)


def site_base(page_host: str) -> str:
    """Approximate first-party base: the page host without a leading 'www.'."""
    host = page_host.lower()
    return host[4:] if host.startswith("www.") else host


def is_first_party(domain: str, page_host: str, extra: tuple[str, ...] | list[str] = ()) -> bool:
    """The page's own domain or a subdomain of it, or of an extra
    first-party domain configured on the website mapping."""
    domain = domain.lower()
    return any(
        domain == base or domain.endswith("." + base)
        for base in [site_base(page_host), *(e.lower() for e in extra)]
    )


def domain_summary(requests: list[dict], page_host: str,
                   extra_first_party: tuple[str, ...] | list[str] = ()) -> list[dict]:
    """Requests, transfer size and time per domain, largest first."""
    rows: dict[str, dict] = {}
    for request in requests:
        domain = request.get("domain") or ""
        if not domain:
            continue
        tech = technology_for_url(request.get("url", ""))
        row = rows.setdefault(domain, {
            "domain": domain,
            "first_party": is_first_party(domain, page_host, extra_first_party),
            "technology": tech.name if tech else "",
            "category": tech.category if tech else "",
            "requests": 0,
            "bytes": 0,
            "total_ms": 0,
            "before_consent": 0,
            "failed": 0,
        })
        row["requests"] += 1
        row["bytes"] += request.get("bytes") or 0
        row["total_ms"] += request.get("duration_ms") or 0
        row["before_consent"] += request.get("phase") == "before_consent"
        row["failed"] += bool(request.get("failed"))
        if tech and not row["technology"]:
            row["technology"], row["category"] = tech.name, tech.category

    return sorted(rows.values(), key=lambda r: (r["first_party"], -r["bytes"], r["domain"]))


def consent_violations(domains: list[dict]) -> list[dict]:
    """Third-party domains contacted before consent that don't have to be."""
    return [
        d for d in domains
        if d["before_consent"] and not d["first_party"]
        and d.get("category") not in EXPECTED_BEFORE_CONSENT
    ]
