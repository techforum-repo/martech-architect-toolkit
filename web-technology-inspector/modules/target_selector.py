"""Select detected website resources for investigation."""

from urllib.parse import urlsplit


def available_targets(scan_result):
    """Build a deduplicated list of observed resources."""

    if not scan_result:
        return []

    targets = {}

    for request in scan_result.get("requests", []):
        url = request.get("url", "")
        domain = request.get("domain", "")

        if domain:
            targets["Domain: " + domain] = domain

        if url and urlsplit(url).scheme in ("http", "https"):
            targets["Resource: " + url] = url

    for script in scan_result.get("scripts", []):
        if script:
            targets["Script: " + script] = script

    return [
        {"label": label, "value": value}
        for label, value in sorted(targets.items())
    ]
