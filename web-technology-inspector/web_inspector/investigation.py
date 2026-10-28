"""Run one investigation: browser scan, detection, AEM page lookup.

Each stage records its own status, so a failure in one (for example an
expired AEM token) keeps the results of the others.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import aem_lookup, mock_scan
from .attribution import investigate
from .detection import detect_technologies, domain_summary
from .errors import friendly_error
from .logging_setup import get_logger
from .mapping import resolve
from .site_config import match
from .token_store import token_status
from .url_safety import validate_public_url


def _same_domain_mapping(url: str, mappings: list[dict]) -> dict | None:
    """A vanity URL sits outside every mapped prefix; any mapping for the
    same domain still tells us which AEM environment to ask."""
    host = (urlsplit(url).hostname or "").lower()
    return next((m for m in mappings if m["published_domain"].lower() == host), None)


def environment_token(environment: dict, session_tokens: dict | None) -> dict:
    """token_status() for the environment, preferring a session-only token."""
    if aem_lookup.is_mock(environment):
        return {"status": "available", "message": "Mock environment", "token": "mock-token"}
    identity = environment["id"] + "|" + environment["author_base"].rstrip("/")
    return token_status(environment, session_token=(session_tokens or {}).get(identity))


def run_investigation(url: str, mappings: list[dict], environments: list[dict], *,
                      mock: bool, device: str = "desktop", consent: str = "none",
                      show_browser: bool = False, timeout: int = 45, settle: int = 6,
                      session_tokens: dict | None = None) -> dict:
    log = get_logger()
    result = {
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device": device,
        "mock": mock,
        "stages": {},
        "browser": None,
        "technologies": [],
        "domains": [],
        "mapping": None,
        "environment": None,
        "aem_page": None,
    }

    def stage(name, status, detail=""):
        result["stages"][name] = {"status": status, "detail": detail}

    mapping = match(url, mappings) or _same_domain_mapping(url, mappings)
    if not mapping:
        stage("mapping", "unavailable", "No website mapping for this domain (see Settings)")
        return result
    result["mapping"] = mapping["name"]
    stage("mapping", "complete")

    # Browser scan
    try:
        if mock:
            browser = mock_scan.sample(url, device, consent)
        else:
            validate_public_url(url, {m["published_domain"].lower() for m in mappings})
            from .scanner import scan  # imported late: Playwright is only needed for real scans
            browser = scan(url, device=device, consent=consent, show_browser=show_browser,
                           timeout=timeout, settle=settle)
        result["browser"] = browser
        stage("browser", "complete", f"{len(browser['requests'])} requests")
        log.info("scan url=%s device=%s consent=%s requests=%d", url, device, consent,
                 len(browser["requests"]))
    except Exception as exc:  # noqa: BLE001 - every failure is reported as a stage result
        error = friendly_error(exc)
        stage("browser", "failed", error.title)
        result["browser_error"] = {"title": error.title, "reasons": error.reasons}
        log.warning("scan failed url=%s error=%s: %s", url, type(exc).__name__, exc)

    browser = result["browser"]
    if browser:
        result["technologies"] = detect_technologies(
            browser["requests"], browser["scripts"], browser.get("globals", []))
        result["domains"] = domain_summary(browser["requests"], urlsplit(url).hostname or "")
        stage("technologies", "complete", f"{len(result['technologies'])} detected")
    else:
        stage("technologies", "unavailable")

    # AEM page lookup
    environment = next((e for e in environments if e["id"] == mapping["environment_id"]), None)
    if not environment:
        stage("aem", "unavailable", "The mapping's AEM environment is not configured")
        return result
    result["environment"] = environment

    auth = environment_token(environment, session_tokens)
    if auth["status"] in ("missing", "expired", "unavailable"):
        stage("aem", "unavailable", auth["message"])
        return result

    try:
        content_path = resolve(url, mapping, environment)["content_path"]
    except ValueError:
        content_path = None

    page = None
    if content_path:
        page = aem_lookup.verify_page(environment, content_path, auth["token"])
        page["method"] = "Prefix mapping, confirmed on author"
    if not page or page["status"] != "found":
        vanity = aem_lookup.find_vanity(environment, urlsplit(url).path, auth["token"])
        if vanity["status"] == "found":
            page = aem_lookup.verify_page(environment, vanity["pages"][0], auth["token"])
            page["method"] = f"Vanity URL {vanity['vanity']}"
        elif page is None:
            page = {"status": "not_found", "message": "Outside the mapped prefix and no vanity URL matched"}

    result["aem_page"] = page
    stage("aem", "complete" if page["status"] == "found" else page["status"],
          page.get("content_path", "") or page.get("message", ""))
    return result


def analyze_target(result: dict, target: str, *, session_tokens: dict | None = None,
                   search_aem: bool = True) -> dict:
    """Browser attribution plus, optionally, AEM references for one target."""
    findings = investigate(result["browser"], target) if result.get("browser") and target.strip() else []
    references: list[dict] = []
    environment = result.get("environment")
    if search_aem and environment and target.strip():
        auth = environment_token(environment, session_tokens)
        if auth.get("token"):
            references = aem_lookup.search_references(environment, target.strip(), auth["token"])
    return {"findings": findings, "aem_references": references}
