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
               hosts=(r"(^|\.)adobedc\.net$",), urls=(r"/alloy(\.min)?\.js(\?|$)",),
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


def technology_for_url(url: str, *, tag_managers_only: bool = False) -> Technology | None:
    """The first technology whose host or URL signature matches."""
    for tech in TECHNOLOGIES:
        if tag_managers_only and not tech.tag_manager:
            continue
        if _matches(tech, url):
            return tech
    return None


def detect_technologies(requests: list[dict], scripts: list[str], page_globals: list[str]) -> list[dict]:
    """One row per detected technology, with the evidence that matched."""
    resources = list(dict.fromkeys([r.get("url", "") for r in requests] + list(scripts)))
    present = set(page_globals or [])
    results = []

    for tech in TECHNOLOGIES:
        global_hits = [name for name in tech.globals if name in present]
        url_hits = [url for url in resources if url and _matches(tech, url)]
        if not global_hits and not url_hits:
            continue
        results.append({
            "technology": tech.name,
            "category": tech.category,
            # A global means the library executed; a request alone means it was fetched.
            "confidence": "Confirmed (ran on the page)" if global_hits else "Observed (loaded)",
            "evidence": [f"window.{name}" for name in global_hits] + url_hits[:20],
        })

    return results


def site_base(page_host: str) -> str:
    """Approximate first-party base: the page host without a leading 'www.'."""
    host = page_host.lower()
    return host[4:] if host.startswith("www.") else host


def is_first_party(domain: str, page_host: str) -> bool:
    base = site_base(page_host)
    domain = domain.lower()
    return domain == base or domain.endswith("." + base)


def domain_summary(requests: list[dict], page_host: str) -> list[dict]:
    """Requests, transfer size and time per domain, largest first."""
    rows: dict[str, dict] = {}
    for request in requests:
        domain = request.get("domain") or ""
        if not domain:
            continue
        tech = technology_for_url(request.get("url", ""))
        row = rows.setdefault(domain, {
            "domain": domain,
            "first_party": is_first_party(domain, page_host),
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
