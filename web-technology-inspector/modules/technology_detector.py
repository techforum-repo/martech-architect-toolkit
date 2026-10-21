"""Technology signature detection."""

from urllib.parse import urlparse

SIGNATURES = {
    "Adobe Tags": [
        "assets.adobedtm.com",
        "satelliteLib-",
        "launch-",
    ],
    "Adobe Analytics": [
        "omtrdc.net",
        "2o7.net",
        "AppMeasurement",
    ],
    "Adobe Target": [
        "at.js",
        "tt.omtrdc.net",
        "delivery-api",
    ],
    "Google Tag Manager": [
        "googletagmanager.com/gtm.js",
        "gtm.js?id=",
    ],
    "Google Analytics": [
        "google-analytics.com",
        "googletagmanager.com/gtag/js",
    ],
    "Tealium": [
        "tags.tiqcdn.com",
        "utag.js",
    ],
    "Ensighten": [
        "nexus.ensighten.com",
        "ensighten.com",
    ],
    "OneTrust": [
        "cdn.cookielaw.org",
        "otSDKStub.js",
    ],
    "Cloudflare": [
        "cdnjs.cloudflare.com",
        "cloudflareinsights.com",
    ],
}


def detect_technologies(requests, scripts):
    """Detect technologies using observable signatures."""
    resources = [
        r.get("url", "") for r in requests
    ] + list(scripts)

    results = []

    for technology, signatures in SIGNATURES.items():
        evidence = []

        for resource in resources:
            if any(
                signature.lower() in resource.lower()
                for signature in signatures
            ):
                evidence.append(resource)

        if evidence:
            results.append({
                "technology": technology,
                "evidence": list(dict.fromkeys(evidence)),
                "classification": "Signature detected",
            })

    return results


def third_party_domains(requests, page_url):
    page_host = urlparse(page_url).hostname
    domains = {}

    for request in requests:
        domain = request.get("domain", "")

        if domain and domain != page_host:
            domains[domain] = domains.get(domain, 0) + 1

    return [
        {"domain": domain, "requests": count}
        for domain, count in sorted(
            domains.items(),
            key=lambda item: -item[1]
        )
    ]
