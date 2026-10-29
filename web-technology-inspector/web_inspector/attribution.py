"""How a domain, script or value reached the page, from browser evidence.

Findings are grouped by what loaded the matching requests (a tag manager,
a specific script, or nothing identifiable), so a busy domain gives a few
findings rather than one per request. AEM references are looked up
separately (aem_lookup) because they need an author token.
"""

from __future__ import annotations

from .detection import technology_for_url

MAX_EXAMPLES = 5


def _tag_manager(urls: list[str]) -> str | None:
    for url in urls:
        tech = technology_for_url(url, tag_managers_only=True)
        if tech:
            return tech.name
    return None


def investigate(scan_result: dict, target: str) -> list[dict]:
    """Correlate a target (domain, URL or text) with the scan's evidence."""
    target = target.strip().lower()
    if not target:
        return []

    requests = scan_result.get("requests", [])
    findings = []

    direct_scripts = [s for s in scan_result.get("scripts", []) if target in s.lower()]
    if direct_scripts:
        findings.append({
            "source": "HTML script element",
            "method": "The page's HTML contains a <script src> for this target",
            "confidence": "Confirmed",
            "requests": len(direct_scripts),
            "evidence": direct_scripts[:MAX_EXAMPLES],
            "explanation": (
                "Rendered directly into the page HTML, so it comes from the page's "
                "template, component or server code rather than a tag manager."
            ),
        })

    inline = [
        i for i, source in enumerate(scan_result.get("inline_scripts", []))
        if target in source.lower()
    ]
    if inline:
        findings.append({
            "source": "Inline JavaScript",
            "method": "The target appears inside an inline <script> block",
            "confidence": "Confirmed",
            "requests": len(inline),
            "evidence": [f"Inline script #{i}" for i in inline[:MAX_EXAMPLES]],
            "explanation": (
                "Embedded in the page HTML. It may come from an authored component "
                "(see AEM evidence), the page template, or server code."
            ),
        })

    relevant = [
        r for r in requests
        if target in r.get("url", "").lower() or target in r.get("initiator_url", "").lower()
    ]

    # Group by what loaded each request.
    groups: dict[tuple[str, str], list[dict]] = {}
    for request in relevant:
        chain = [request.get("initiator_url", "")] + request.get("stack_urls", [])
        manager = _tag_manager([u for u in chain if u])
        if manager:
            key = ("manager", manager)
        elif request.get("initiator_url"):
            key = ("script", request["initiator_url"])
        else:
            key = ("unknown", request.get("initiator_type") or "unknown")
        groups.setdefault(key, []).append(request)

    for (kind, name), items in groups.items():
        examples = list(dict.fromkeys(r.get("url", "") for r in items))[:MAX_EXAMPLES]
        before_consent = sum(r.get("phase") == "before_consent" for r in items)
        consent_note = (
            f" {before_consent} of these fired before consent was given." if before_consent else ""
        )
        if kind == "manager":
            finding = {
                "source": name,
                "method": "The browser's initiator chain passes through this tag manager",
                "confidence": "Probable",
                "explanation": "Loaded by a script that belongs to " + name + "." + consent_note,
            }
        elif kind == "script":
            finding = {
                "source": "Script: " + name,
                "method": "Chromium recorded this script as the initiator",
                "confidence": "Confirmed",
                "explanation": "Requested by the script shown." + consent_note,
            }
        else:
            finding = {
                "source": "Unresolved (" + name + ")",
                "method": "No script initiator was recorded",
                "confidence": "Unknown",
                "explanation": (
                    "Typically a request made by the HTML itself (an image, stylesheet or "
                    "iframe) or by a redirect." + consent_note
                ),
            }
        finding.update(requests=len(items), evidence=examples)
        findings.append(finding)

    if not findings and " " in target:
        # Text, not a domain or URL: it's shown on the page, not loaded by a request.
        findings.append({
            "source": "Page text",
            "method": "Text isn't loaded by a request or script",
            "confidence": "n/a",
            "requests": 0,
            "evidence": [],
            "explanation": (
                "This section traces how requests and scripts load. Text shown on the page comes "
                "from the content itself: Search AEM below finds the component or page that holds it."
            ),
        })
    if not findings:
        findings.append({
            "source": "Not found",
            "method": "No matching evidence",
            "confidence": "Unknown",
            "requests": 0,
            "evidence": [],
            "explanation": "Nothing in this scan's requests, scripts or inline code matches the target.",
        })

    return findings
