"""A realistic sample browser scan, used in mock mode instead of Chromium.

It mirrors what scanner.scan() returns for a page with Adobe Tags, the
Web SDK, a vendor pixel added by a tag, a redirect hop, a consent banner,
and a tracker that fires before consent.
"""

from __future__ import annotations

PAGE = "https://www.example.com/us/en/products.html"
LAUNCH = "https://assets.adobedtm.com/abc123/def456/launch-0a1b2c3d.min.js"
ALLOY = "https://www.example.com/etc.clientlibs/example/clientlibs/clientlib-analytics/alloy.min.js"
PIXEL = "https://tracking.example.com/pixel.gif?event=pageview"


def _request(url, *, initiator="", initiator_type="parser", type_="Script", status=200,
             size=1200, ms=80, phase="before_consent", **extra):
    domain = url.split("/")[2]
    return dict({
        "url": url, "domain": domain, "method": "GET", "type": type_,
        "initiator_type": initiator_type, "initiator_url": initiator,
        "stack_urls": [initiator] if initiator else [], "redirect_from": "",
        "redirected_to": "", "status": status, "mime_type": "", "bytes": size,
        "duration_ms": ms, "failed": "", "phase": phase,
    }, **extra)


def sample(url: str = PAGE, device: str = "desktop", consent: str = "accept") -> dict:
    accepted = consent == "accept"
    after = "after_consent" if accepted else "page_load"
    before = "before_consent" if accepted else "page_load"
    requests = [
        _request(url, type_="Document", initiator_type="other", size=48_000, ms=220, phase=before),
        _request(LAUNCH, size=96_000, ms=140, phase=before),
        _request(ALLOY, size=88_000, ms=110, phase=before),
        _request("https://cdn.cookielaw.org/scripttemplates/otSDKStub.js", size=21_000, phase=before),
        # Fires before consent: the finding a consent audit is for.
        _request("https://www.googletagmanager.com/gtag/js?id=G-EXAMPLE", initiator=LAUNCH,
                 initiator_type="script", size=110_000, ms=160, phase=before),
        _request("https://edge.adobedc.net/ee/v1/interact?configId=abc", initiator=ALLOY,
                 initiator_type="script", type_="Fetch", size=3_400, ms=190, phase=after),
        _request("https://tracking.example.com/redirect?id=1", initiator=LAUNCH, initiator_type="script",
                 type_="Image", status=302, size=400, ms=60, phase=after,
                 redirected_to=PIXEL),
        _request(PIXEL, initiator=LAUNCH, initiator_type="script", type_="Image", size=43, ms=45,
                 phase=after, redirect_from="https://tracking.example.com/redirect?id=1"),
        _request("https://connect.facebook.net/en_US/fbevents.js", initiator=LAUNCH,
                 initiator_type="script", size=95_000, ms=120, phase=after),
        _request("https://www.example.com/etc.clientlibs/example/clientlibs/clientlib-site.min.css",
                 type_="Stylesheet", size=64_000, ms=70, phase=before),
    ]
    cookies_before = [
        {"name": "OptanonConsent", "domain": "example.com", "path": "/", "session": False,
         "expires": 1830000000, "http_only": False, "secure": True, "same_site": "Lax"},
        {"name": "_ga", "domain": "example.com", "path": "/", "session": False,
         "expires": 1830000000, "http_only": False, "secure": False, "same_site": "Lax"},
    ]
    cookies_after = cookies_before + [
        {"name": "kndctr_ABC_AdobeOrg_identity", "domain": "example.com", "path": "/",
         "session": False, "expires": 1830000000, "http_only": False, "secure": True, "same_site": "None"},
        {"name": "_fbp", "domain": "example.com", "path": "/", "session": False,
         "expires": 1830000000, "http_only": False, "secure": False, "same_site": "Lax"},
    ]
    return {
        "url": url,
        "final_url": url,
        "title": "Products | Example",
        "main_status": 200,
        "device": device,
        "user_agent": "Mozilla/5.0 (mock scan)",
        "consent": {"mode": consent, "platform": "OneTrust" if accepted else None, "accepted": accepted},
        "requests": requests,
        "scripts": [LAUNCH, ALLOY, "https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"],
        "inline_scripts": ["window.adobeDataLayer = window.adobeDataLayer || [];"],
        "iframes": [],
        "globals": ["_satellite", "alloy", "__alloyNS", "adobeDataLayer", "OneTrust", "gtag", "fbq"],
        "cookies_before_consent": cookies_before if accepted else None,
        "cookies": cookies_after if accepted else cookies_before,
        "screenshot": None,
    }
