"""Unified, read-only investigation orchestrator."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from modules.scanner import scan
from modules.config_manager import match
from modules.mapping import resolve
from modules.aem_auth import token_status
from modules.aem import inspect_page
from modules.technology_detector import detect_technologies
from modules.attribution_engine import investigate
from modules.advanced import (
    validate_public_url,
    request_graph,
    inventory,
)
from modules.page_investigator import (
    search_properties,
    page_summary,
)


def run_investigation(url, mappings, environments, session_tokens=None):
    """Run stages independently and preserve partial results."""

    result = {
        "url": url,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "stages": {},
        "browser": None,
        "aem": None,
        "technologies": [],
        "mapping": None,
        "content_path": None,
        "screenshot": None,
    }

    def stage(name, status, detail=""):
        result["stages"][name] = {
            "status": status,
            "detail": detail,
        }

    mapping = match(url, mappings)

    if not mapping:
        stage("mapping", "unavailable",
              "No matching website configuration")
        return result

    result["mapping"] = mapping["name"]
    stage("mapping", "complete")

    approved = {
        m["published_domain"].lower()
        for m in mappings
    }

    # Browser scan
    try:
        validate_public_url(url, approved)
        browser = scan(url)
        result["browser"] = browser
        stage("browser", "complete")
    except Exception as exc:
        stage("browser", "failed", type(exc).__name__)

    # Technology detection
    if result["browser"]:
        try:
            result["technologies"] = detect_technologies(
                result["browser"].get("requests", []),
                result["browser"].get("scripts", [])
            )
            stage("technologies", "complete")
        except Exception as exc:
            stage("technologies", "failed",
                  type(exc).__name__)
    else:
        stage("technologies", "unavailable")

    # AEM inspection
    environment = next(
        (
            e for e in environments
            if e["id"] == mapping["environment_id"]
        ),
        None
    )

    if not environment:
        stage("aem", "unavailable",
              "AEM environment not configured")
        return result

    try:
        resolved = resolve(url, mapping, environment)
        result["content_path"] = resolved["content_path"]

        identity = (
            environment["id"]
            + "|"
            + environment["author_base"].rstrip("/")
        )

        session_token = (
            (session_tokens or {}).get(identity)
        )

        auth = token_status(
            environment,
            session_token=session_token
        )

        if auth["status"] in (
            "missing", "expired", "unavailable"
        ):
            stage("aem", "unavailable", auth["message"])
        else:
            result["aem"] = inspect_page(
                resolved["json_url"],
                auth["token"]
            )
            stage("aem", "complete")

    except Exception as exc:
        stage("aem", "failed", type(exc).__name__)

    return result


def analyze_target(result, target):
    """Correlate existing browser and AEM evidence."""
    if not target.strip():
        return {"findings": [], "properties": []}

    browser = result.get("browser")
    content = result.get("aem")

    properties = (
        search_properties(
            content,
            target,
            max_depth=20,
            max_nodes=5000,
            max_results=200
        )
        if content is not None else []
    )

    findings = (
        investigate(browser, target, content)
        if browser is not None else []
    )

    return {
        "findings": findings,
        "properties": properties,
    }


def safe_report(result, analysis):
    """Build report without raw AEM JSON or credentials."""
    browser = result.get("browser") or {}

    return {
        "application": "Web Technology Inspector",
        "version": "0.9",
        "url": result["url"],
        "timestamp": result["timestamp"],
        "stages": result["stages"],
        "mapping": result["mapping"],
        "content_path": result["content_path"],
        "technologies": result["technologies"],
        "request_count": len(
            browser.get("requests", [])
        ),
        "script_count": len(
            browser.get("scripts", [])
        ),
        "attribution": analysis["findings"],
        "property_matches": analysis["properties"],
        "limitations": [
            "Exact tag-manager rules are not verified.",
            "AEM content is limited to accessible endpoints.",
            "Property matches do not prove request causation.",
            "Dialog field definitions may be unavailable."
        ]
    }

