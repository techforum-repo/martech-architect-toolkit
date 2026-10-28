"""Reports and exports built from a scan. No AEM tokens, cookie values,
inline script contents or screenshots are included."""

from __future__ import annotations

import csv
import io
import json
from html import escape

from . import VERSION
from .detection import EXPECTED_BEFORE_CONSENT, consent_violations

CSV_COLUMNS = (
    "url", "domain", "method", "type", "status", "mime_type", "bytes", "duration_ms",
    "phase", "initiator_type", "initiator_url", "redirect_from", "redirected_to", "failed",
)


def build_report(result: dict, findings: list[dict], aem_references: list[dict], target: str = "") -> dict:
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
        "target": target.strip(),
        "attribution": findings,
        "aem_references": aem_references,
        "limitations": [
            "Tags that fire later than the settle time, or only after user interaction, are not captured.",
            "Tag-manager attribution is from the browser initiator chain; the exact rule is not identified.",
            "AEM references show where a value is stored, not proof that it caused a request.",
            "Full-text search depends on the AEM search index; unindexed code may not be found.",
        ],
    }


REPORT_CSS = """
:root{--fg:#1d1d1f;--muted:#5f6368;--line:#dadce0;--bg:#fff;--card:#f8f9fa;--warn:#b3261e;--ok:#1e7d34}
@media (prefers-color-scheme: dark){:root{--fg:#e8eaed;--muted:#9aa0a6;--line:#3c4043;--bg:#202124;--card:#292a2d;--warn:#f28b82;--ok:#81c995}}
body{font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg);
  max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.meta{color:var(--muted);margin:0 0 16px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.card b{display:block;font-size:1.4rem}.card span{color:var(--muted);font-size:.85rem}
table{border-collapse:collapse;width:100%;font-size:.9rem;margin:8px 0}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;word-break:break-word}
th{background:var(--card)}td.n{text-align:right;white-space:nowrap}
.warn{color:var(--warn);font-weight:600}.ok{color:var(--ok);font-weight:600}.muted{color:var(--muted)}
code{font-size:.85rem;word-break:break-all}
@media print{body{max-width:none}.card{break-inside:avoid}}
"""


def _table(headers: list[str], rows: list[list], numeric: tuple[int, ...] = ()) -> str:
    if not rows:
        return "<p class='muted'>None.</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(
            f"<td class='n'>{escape(str(v))}</td>" if i in numeric else f"<td>{escape(str(v))}</td>"
            for i, v in enumerate(row)
        ) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def stage_label(name: str) -> str:
    return "AEM" if name == "aem" else name.title()


def _kb(size: int) -> str:
    return f"{(size or 0) / 1000:,.0f} KB"


def html_report(report: dict) -> str:
    """A self-contained, readable report for sharing (no external assets)."""
    domains = report.get("domains", [])
    third = [d for d in domains if not d["first_party"]]
    consent = report.get("consent") or {}
    audited = consent.get("mode") == "accept"
    violations = consent_violations(domains)
    target = report.get("target") or ""

    cards = [
        (report.get("request_count", 0), "Requests"),
        (len(report.get("technologies", [])), "Technologies"),
        (len(third), "Third-party domains"),
        (f"{sum(d['bytes'] for d in third) / 1_000_000:.2f} MB", "Third-party weight"),
    ]
    if audited:
        cards.append((len(violations), "Tracked before consent"))

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Inspection: {escape(report['url'])}</title><style>{REPORT_CSS}</style></head><body>",
        "<h1>Web Technology Inspection</h1>",
        f"<p class='meta'>{escape(report['url'])}<br>Scanned {escape(report['timestamp'][:16].replace('T', ' '))} UTC"
        f" · {escape(str(report.get('device') or '').title())}"
        + (" · <b>sample data (mock mode)</b>" if report.get("mock") else "") + "</p>",
        "<div class='cards'>" + "".join(
            f"<div class='card'><b>{escape(str(v))}</b><span>{escape(label)}</span></div>" for v, label in cards
        ) + "</div>",
    ]

    parts.append("<h2>Consent</h2>")
    if not audited:
        parts.append("<p class='muted'>Not audited: the scan left the consent banner alone.</p>")
    elif not consent.get("accepted"):
        parts.append("<p class='warn'>No known consent banner was found, so nothing was accepted. "
                     "Everything below loaded without an explicit consent click.</p>")
    else:
        verdict = (f"<span class='warn'>{len(violations)} third-party domain(s) tracked before consent.</span>"
                   if violations else "<span class='ok'>No third-party tracking before consent.</span>")
        parts.append(f"<p>Accepted the {escape(consent.get('platform') or '')} banner during the scan. {verdict}</p>")
        early = [d for d in third if d["before_consent"]]
        parts.append(_table(
            ["Domain", "Technology", "Requests before consent", "Assessment"],
            [[d["domain"], d["technology"] or "Unknown", d["before_consent"],
              "Expected: " + d["category"].lower() if d.get("category") in EXPECTED_BEFORE_CONSENT else "Review"]
             for d in early], numeric=(2,)))

    parts.append("<h2>Technologies</h2>")
    parts.append(_table(["Technology", "Category", "Evidence", "Example"],
                        [[t["technology"], t["category"], t["confidence"], (t["evidence"] or [""])[0]]
                         for t in report.get("technologies", [])]))

    parts.append("<h2>Third parties</h2>")
    parts.append(_table(["Domain", "Technology", "Requests", "Transferred", "Total time", "Before consent"],
                        [[d["domain"], d["technology"] or "", d["requests"], _kb(d["bytes"]),
                          f"{d['total_ms']:,} ms", d["before_consent"] if audited else "n/a"] for d in third],
                        numeric=(2, 3, 4, 5)))

    before = {(c["name"], c["domain"]) for c in report.get("cookies_before_consent") or []}
    parts.append("<h2>Cookies</h2><p class='muted'>Names only; cookie values are never read into reports.</p>")
    parts.append(_table(["Name", "Domain", "Set", "Lifetime", "Secure", "HttpOnly", "SameSite"],
                        [[c["name"], c["domain"],
                          ("Before consent" if (c["name"], c["domain"]) in before else "After consent")
                          if audited and consent.get("accepted") else "During page load",
                          "Session" if c["session"] else "Persistent", c["secure"], c["http_only"], c["same_site"]]
                         for c in report.get("cookies", [])]))

    aem_page = report.get("aem_page") or {}
    parts.append("<h2>AEM</h2>")
    if aem_page.get("status") == "found":
        parts.append(f"<p>Page <code>{escape(aem_page['content_path'])}</code> "
                     f"<span class='muted'>({escape(aem_page.get('method', ''))})</span><br>"
                     f"Template <code>{escape(aem_page.get('template') or '')}</code></p>")
    else:
        parts.append("<p class='muted'>The AEM page was not identified for this scan.</p>")

    if target:
        parts.append(f"<h2>How “{escape(target)}” was added</h2>")
        parts.append(_table(["Source", "Confidence", "Requests", "Explanation", "Example"],
                            [[f["source"], f["confidence"], f["requests"], f["explanation"],
                              (f["evidence"] or [""])[0]] for f in report.get("attribution", [])],
                            numeric=(2,)))
        references = [h for r in report.get("aem_references", []) for h in r["hits"]]
        if report.get("aem_references"):
            parts.append(f"<h2>Where AEM references “{escape(target)}”</h2>")
            parts.append(_table(["Node", "Page", "Component"],
                                [[h["node_path"], h["page_path"], h["resource_type"]] for h in references]))

    parts.append("<h2>Scan stages</h2>")
    parts.append(_table(["Stage", "Status", "Details"],
                        [[stage_label(name), s["status"], s["detail"]] for name, s in report.get("stages", {}).items()]))
    parts.append("<h2>Limitations</h2><ul>" + "".join(
        f"<li>{escape(item)}</li>" for item in report.get("limitations", [])) + "</ul>")
    parts.append(f"<p class='muted'>{escape(report['application'])} {escape(report['version'])} · "
                 "read-only findings; attribution may be incomplete.</p></body></html>")
    return "\n".join(parts)


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
