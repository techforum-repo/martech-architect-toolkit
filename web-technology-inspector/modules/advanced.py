"""Bounded, read-only investigation utilities."""
import ipaddress
import json
import re
import socket
from collections import Counter
from urllib.parse import urlsplit

PRIVATE = ("localhost", "localhost.localdomain")

def validate_public_url(url, allowed_hosts):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443) or host not in allowed_hosts
            or host in PRIVATE):
        raise ValueError("URL must be HTTPS on a configured, approved website hostname")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Website hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Non-public or ambiguous DNS destination rejected")
    return host

def request_graph(scan_result, max_edges=120):
    """Build a browser-observed dependency graph, without asserting tag rule identity."""
    requests = scan_result.get("requests", [])
    edges = []
    for req in requests:
        child = req.get("url", "")
        parent = req.get("initiator_url", "")
        if not parent:
            stack = req.get("stack_urls") or []
            parent = stack[0] if stack else ""
        if parent and child and parent != child:
            edges.append((parent, child))
        if len(edges) >= max_edges:
            break
    return edges

def dot_graph(edges):
    def quote(value):
        label = value.split("?")[0][-90:]
        return json.dumps(label)
    lines = ["digraph Requests {", 'rankdir="LR";', 'node [shape=box, fontsize=10];']
    for a, b in edges:
        lines.append(f"{quote(a)} -> {quote(b)};")
    lines.append("}")
    return "\n".join(lines)

def inventory(scans):
    rows = []
    for page, data in scans.items():
        domains = Counter(r.get("domain", "") for r in data.get("requests", []) if r.get("domain"))
        for domain, count in domains.items():
            rows.append({"page": page, "domain": domain, "requests": count})
    return rows

def inspect_dialog_hints(matches):
    """Potential field names only; not authoritative Granite UI definitions."""
    return [{"node_path": m.get("node_path", ""),
             "property": m.get("property", ""),
             "field_name_candidate": "./" + m.get("property", ""),
             "resource_type": m.get("resource_type", ""),
             "dialog_verified": False} for m in matches]

def html_report(data):
    from html import escape
    body = ["<!doctype html><html><head><meta charset='utf-8'><title>Investigation Report</title></head><body>",
            "<h1>Web Technology Inspector Report</h1>",
            "<p>Read-only findings. Source attribution may be incomplete.</p>"]
    for key, value in data.items():
        body.append(f"<h2>{escape(str(key))}</h2><pre>{escape(json.dumps(value, indent=2, default=str))}</pre>")
    body.append("</body></html>")
    return "\n".join(body)
