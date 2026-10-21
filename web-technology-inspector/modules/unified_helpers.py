"""Utilities for unified, read-only investigations."""

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pandas as pd


def request_table(result):
    rows = []

    for request in result.get("requests", []):
        status = request.get("status")

        rows.append({
            "domain": str(request.get("domain") or ""),
            "url": str(request.get("url") or ""),
            "type": str(request.get("type") or ""),
            "status": (
                str(status) if status is not None else ""
            ),
            "initiator": str(
                request.get("initiator_url") or ""
            ),
            "initiator_type": str(
                request.get("initiator_type") or ""
            )
        })

    return pd.DataFrame(rows, columns=[
        "domain", "url", "type", "status",
        "initiator", "initiator_type"
    ])


def matching_requests(result, target):
    df = request_table(result)

    if df.empty or not target.strip():
        return df

    mask = df.astype(str).apply(
        lambda col: col.str.contains(
            target.strip(),
            case=False,
            regex=False
        )
    ).any(axis=1)

    return df.loc[mask].copy()


def summary(result, page_url):
    requests = result.get("requests", [])
    host = urlsplit(page_url).hostname

    domains = {
        request.get("domain")
        for request in requests
        if request.get("domain")
        and request.get("domain") != host
    }

    return {
        "requests": len(requests),
        "scripts": len(result.get("scripts", [])),
        "third_party_domains": len(domains),
        "iframes": len(result.get("iframes", []))
    }


def make_report(
    url,
    target,
    scan_result,
    findings,
    property_matches,
    content_path
):
    return {
        "application": "Web Technology Inspector",
        "report_version": "0.7",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "page_url": url,
        "investigation_target": target,
        "summary": summary(scan_result, url),
        "detected_scripts": scan_result.get(
            "scripts", []
        ),
        "attribution_findings": findings,
        "aem_content_path": content_path,
        "aem_property_matches": property_matches,
        "limitations": [
            "Browser evidence may not identify exact tag rules.",
            "AEM properties are limited to retrieved content.",
            "Dialog definitions are not automatically verified.",
            "A property match does not prove request causation."
        ]
    }
