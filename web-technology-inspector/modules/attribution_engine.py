"""Evidence-based technology attribution."""

from urllib.parse import urlparse

from modules.technology_detector import SIGNATURES
from modules.page_investigator import search_properties


def _tag_system(url):
    value = url.lower()

    for name in (
        "Adobe Tags",
        "Google Tag Manager",
        "Tealium",
        "Ensighten",
    ):
        for signature in SIGNATURES.get(name, []):
            if signature.lower() in value:
                return name

    return None


def investigate(scan_result, target, aem_content=None):
    """Correlate browser and available AEM evidence."""
    target = target.strip().lower()

    if not target:
        return []

    requests = scan_result.get("requests", [])
    scripts = scan_result.get("scripts", [])
    inline_scripts = scan_result.get(
        "inline_scripts", []
    )

    findings = []

    relevant = [
        r for r in requests
        if target in r.get("url", "").lower()
        or target in r.get(
            "initiator_url", ""
        ).lower()
    ]

    direct_scripts = [
        s for s in scripts
        if target in s.lower()
    ]

    inline_matches = [
        index
        for index, source in enumerate(inline_scripts)
        if target in source.lower()
    ]

    aem_matches = []

    if aem_content is not None:
        aem_matches = search_properties(
            aem_content,
            target,
            mode="Contains",
            case_sensitive=False
        )

    if direct_scripts:
        findings.append({
            "source": "HTML script element",
            "method": "Direct script reference",
            "confidence": "Confirmed",
            "evidence": direct_scripts,
            "explanation": (
                "The rendered document contains a "
                "script element referencing this target. "
                "The original configuration is not yet known."
            )
        })

    if inline_matches:
        findings.append({
            "source": "Inline JavaScript",
            "method": "Embedded page script",
            "confidence": "Confirmed",
            "evidence": [
                "Inline script index: " + str(i)
                for i in inline_matches
            ],
            "explanation": (
                "The target appears in inline JavaScript. "
                "This does not establish whether it came "
                "from authoring, a template, or server code."
            )
        })

    for request in relevant:
        initiator = request.get(
            "initiator_url", ""
        )

        stack = request.get(
            "stack_urls", []
        )

        candidate_sources = [
            initiator
        ] + stack

        systems = [
            _tag_system(value)
            for value in candidate_sources
        ]

        systems = [
            system
            for system in systems
            if system
        ]

        system = (
            systems[0]
            if systems else None
        )

        if system:
            findings.append({
                "source": system,
                "method": "Browser initiator chain",
                "confidence": "Probable",
                "evidence": [
                    request.get("url", ""),
                    initiator,
                ] + stack,
                "explanation": (
                    "The browser initiator evidence "
                    "references a recognized tagging "
                    "system. The exact tag or rule "
                    "has not been verified."
                )
            })

        elif initiator:
            findings.append({
                "source": "JavaScript initiator",
                "method": "Script dependency",
                "confidence": "Confirmed",
                "evidence": [
                    request.get("url", ""),
                    initiator,
                ],
                "explanation": (
                    "Chromium identified this script "
                    "as an initiator. Its original "
                    "deployment method remains unknown."
                )
            })

        else:
            findings.append({
                "source": "Unresolved request",
                "method": request.get(
                    "initiator_type", "Unknown"
                ),
                "confidence": "Unknown",
                "evidence": [
                    request.get("url", "")
                ],
                "explanation": (
                    "The request was observed, but "
                    "the available evidence does not "
                    "identify its original source."
                )
            })

    for match in aem_matches:
        findings.append({
            "source": "AEM authored content",
            "method": match["source"],
            "confidence": "Confirmed",
            "evidence": [
                match["node_path"]
                + "/"
                + match["property"]
            ],
            "explanation": (
                "The target was found in a retrieved "
                "AEM property. This confirms the "
                "property reference, not necessarily "
                "that it caused the network request."
            )
        })

    if not findings:
        findings.append({
            "source": "Unknown",
            "method": "No matching evidence",
            "confidence": "Unknown",
            "evidence": [],
            "explanation": (
                "No matching attribution evidence "
                "was found in the available scan "
                "or AEM content."
            )
        })

    return findings
