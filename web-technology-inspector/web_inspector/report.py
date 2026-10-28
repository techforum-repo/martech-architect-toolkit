"""Reports and exports built from a scan. No AEM tokens, cookie values,
inline script contents or screenshots are included."""

from __future__ import annotations

import csv
import io
import json
from html import escape

from . import VERSION

CSV_COLUMNS = (
    "url", "domain", "method", "type", "status", "mime_type", "bytes", "duration_ms",
    "phase", "initiator_type", "initiator_url", "redirect_from", "redirected_to", "failed",
)


def build_report(result: dict, findings: list[dict], aem_references: list[dict]) -> dict:
    browser = result.get("browser") or {}
    return {
        "application": "Web Technology Inspector",
        "version": VERSION,
        "url": result["url"],
        "timestamp": result["timestamp"],
        "device": result.get("device"),
        "mock": result.get("mock", False),
        "stages": result["stages"],
        "mapping": result.get("mapping"),
        "aem_page": result.get("aem_page"),
        "technologies": result["technologies"],
        "domains": result["domains"],
        "consent": browser.get("consent"),
        "cookies": browser.get("cookies", []),
        "cookies_before_consent": browser.get("cookies_before_consent"),
        "request_count": len(browser.get("requests", [])),
        "script_count": len(browser.get("scripts", [])),
        "attribution": findings,
        "aem_references": aem_references,
        "limitations": [
            "Tags that fire later than the settle time, or only after user interaction, are not captured.",
            "Tag-manager attribution is from the browser initiator chain; the exact rule is not identified.",
            "AEM references show where a value is stored, not proof that it caused a request.",
            "Full-text search depends on the AEM search index; unindexed code may not be found.",
        ],
    }


def html_report(report: dict) -> str:
    body = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Investigation Report</title></head><body>",
        "<h1>Web Technology Inspector Report</h1>",
        "<p>Read-only findings. Source attribution may be incomplete.</p>",
    ]
    for key, value in report.items():
        body.append(f"<h2>{escape(str(key))}</h2><pre>{escape(json.dumps(value, indent=2, default=str))}</pre>")
    body.append("</body></html>")
    return "\n".join(body)


def requests_csv(requests: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for request in requests:
        writer.writerow({column: request.get(column, "") for column in CSV_COLUMNS})
    return buffer.getvalue()


def request_graph(browser: dict, max_edges: int = 120) -> list[tuple[str, str]]:
    """Browser-observed parent -> child request edges."""
    edges = []
    for request in browser.get("requests", []):
        child = request.get("url", "")
        parent = request.get("initiator_url", "") or next(iter(request.get("stack_urls") or []), "")
        if parent and child and parent != child:
            edges.append((parent, child))
        if len(edges) >= max_edges:
            break
    return edges


def dot_graph(edges: list[tuple[str, str]]) -> str:
    def quote(value: str) -> str:
        return json.dumps(value.split("?")[0][-90:])

    lines = ["digraph Requests {", 'rankdir="LR";', "node [shape=box, fontsize=10];"]
    lines += [f"{quote(a)} -> {quote(b)};" for a, b in edges]
    lines.append("}")
    return "\n".join(lines)
