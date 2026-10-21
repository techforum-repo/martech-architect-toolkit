"""Content-only AEM investigation utilities."""

import hashlib
import json
from collections import deque, Counter
from datetime import datetime, timezone
from pathlib import Path

HISTORY = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "investigation_history.json"
)

MAX_NODES = 5000
MAX_DEPTH = 20


def inspect_tree(data):
    """Inventory accessible content nodes and properties."""
    rows = []
    queue = deque([(data, "", 0)])
    visited = 0

    while queue and visited < MAX_NODES:
        node, path, depth = queue.popleft()
        visited += 1

        if depth > MAX_DEPTH:
            continue

        if isinstance(node, dict):
            resource_type = str(
                node.get("sling:resourceType", "")
            )

            properties = [
                key for key, value in node.items()
                if not isinstance(value, (dict, list))
            ]

            rows.append({
                "path": path or "/",
                "resource_type": resource_type,
                "property_count": len(properties),
                "properties": ", ".join(properties)
            })

            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    queue.append((
                        value,
                        path + "/" + key,
                        depth + 1
                    ))

        elif isinstance(node, list):
            for index, value in enumerate(node[:200]):
                if isinstance(value, (dict, list)):
                    queue.append((
                        value,
                        path + "/" + str(index),
                        depth + 1
                    ))

    return rows


def component_inventory(data):
    rows = inspect_tree(data)

    return [
        row for row in rows
        if row["resource_type"]
    ]


def page_properties(data):
    """Properties directly under jcr:content."""
    content = data.get("jcr:content", {})

    if not isinstance(content, dict):
        return {}

    return {
        key: value
        for key, value in content.items()
        if not isinstance(value, (dict, list))
    }


def find_matches(data, term, case_sensitive=False):
    """Search property names and scalar values."""
    if not term.strip():
        return []

    results = []
    queue = deque([(data, "", 0)])
    visited = 0

    def contains(value):
        value = str(value)
        needle = term.strip()

        if not case_sensitive:
            value = value.lower()
            needle = needle.lower()

        return needle in value

    while queue and visited < MAX_NODES:
        node, path, depth = queue.popleft()
        visited += 1

        if depth > MAX_DEPTH:
            continue

        if isinstance(node, dict):
            resource_type = node.get(
                "sling:resourceType", ""
            )

            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    queue.append((
                        value,
                        path + "/" + key,
                        depth + 1
                    ))
                    continue

                if contains(key) or contains(value):
                    results.append({
                        "node_path": path or "/",
                        "property": key,
                        "value": str(value)[:500],
                        "resource_type": resource_type,
                        "dialog_field_candidate": "./" + key,
                        "verified_dialog": False
                    })

                    if len(results) >= 500:
                        return results

        elif isinstance(node, list):
            for index, value in enumerate(node[:200]):
                queue.append((
                    value,
                    path + "/" + str(index),
                    depth + 1
                ))

    return results


def scan_summary(url, result):
    """Generate a minimized history record."""
    domains = sorted({
        str(r.get("domain", ""))
        for r in result.get("requests", [])
        if r.get("domain")
    })

    return {
        "id": hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:16],
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "request_count": len(
            result.get("requests", [])
        ),
        "script_count": len(
            result.get("scripts", [])
        ),
        "domains": domains[:200]
    }


def load_history():
    if not HISTORY.exists():
        return []

    try:
        data = json.loads(
            HISTORY.read_text(encoding="utf-8")
        )
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(record):
    HISTORY.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    records = load_history()
    records.append(record)
    records = records[-100:]

    temporary = HISTORY.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(records, indent=2),
        encoding="utf-8"
    )
    temporary.replace(HISTORY)


def compare_scans(a, b):
    old = set(a.get("domains", []))
    new = set(b.get("domains", []))

    return {
        "added_domains": sorted(new - old),
        "removed_domains": sorted(old - new),
        "unchanged_domains": sorted(old & new),
        "request_change": (
            b["request_count"] - a["request_count"]
        ),
        "script_change": (
            b["script_count"] - a["script_count"]
        )
    }
