from __future__ import annotations

"""Scan history in SQLite, so a page's scans can be compared over time.

Only a compact summary of each scan is stored (technologies, domains,
cookie names, consent findings), never request bodies, cookie values,
inline scripts or screenshots. The file is restricted to the owning user.
"""

import json
import sqlite3
from contextlib import closing

from .config import settings
from .detection import consent_violations
from .utils import harden_file_permissions

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    device TEXT NOT NULL,
    consent TEXT NOT NULL,
    mock INTEGER NOT NULL,
    summary TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS scans_url ON scans (url, device, scanned_at);
"""


def _connect() -> sqlite3.Connection:
    directory = settings.data_path
    directory.mkdir(parents=True, exist_ok=True)
    harden_file_permissions(directory, mode=0o700)
    path = directory / "inspector.db"
    connection = sqlite3.connect(path)
    harden_file_permissions(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize() -> None:
    with closing(_connect()) as connection:
        connection.executescript(SCHEMA)


def summarize(result: dict) -> dict:
    """The compact, comparable part of an investigation."""
    browser = result.get("browser") or {}
    before = browser.get("cookies_before_consent")
    return {
        "title": browser.get("title", ""),
        "main_status": browser.get("main_status"),
        "technologies": sorted(t["technology"] for t in result.get("technologies", [])),
        "domains": {
            d["domain"]: {"requests": d["requests"], "bytes": d["bytes"], "first_party": d["first_party"]}
            for d in result.get("domains", [])
        },
        "cookies": sorted({f"{c['name']} ({c['domain']})" for c in browser.get("cookies", [])}),
        "consent_accepted": (browser.get("consent") or {}).get("accepted", False),
        "before_consent_domains": sorted(d["domain"] for d in consent_violations(result.get("domains", []))),
        "before_consent_cookies": sorted({f"{c['name']} ({c['domain']})" for c in before or []}),
        "aem_page": (result.get("aem_page") or {}).get("content_path"),
    }


def save_scan(result: dict, consent: str) -> int:
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO scans (url, scanned_at, device, consent, mock, summary) VALUES (?, ?, ?, ?, ?, ?)",
            (result["url"], result["timestamp"], result["device"], consent, int(result["mock"]),
             json.dumps(summarize(result))),
        )
        return cursor.lastrowid


def _row(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["summary"] = json.loads(record["summary"])
    record["mock"] = bool(record["mock"])
    return record


def list_scans(url: str | None = None, limit: int = 200) -> list[dict]:
    query = "SELECT * FROM scans"
    params: tuple = ()
    if url:
        query += " WHERE url = ?"
        params = (url,)
    query += " ORDER BY scanned_at DESC, id DESC LIMIT ?"
    with closing(_connect()) as connection:
        return [_row(r) for r in connection.execute(query, params + (limit,))]


def get_scan(scan_id: int) -> dict | None:
    with closing(_connect()) as connection:
        row = connection.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return _row(row) if row else None


def previous_scan(scan_id: int) -> dict | None:
    """The scan of the same URL, device and mode (real or mock) just before this one."""
    current = get_scan(scan_id)
    if not current:
        return None
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM scans WHERE url = ? AND device = ? AND mock = ? AND id < ? "
            "ORDER BY id DESC LIMIT 1",
            (current["url"], current["device"], int(current["mock"]), scan_id),
        ).fetchone()
    return _row(row) if row else None


def compare(old: dict, new: dict) -> dict:
    """What changed between two scan summaries."""
    def change(key):
        before, after = set(old.get(key, [])), set(new.get(key, []))
        return {"added": sorted(after - before), "removed": sorted(before - after)}

    return {
        "technologies": change("technologies"),
        "domains": change("domains"),
        "cookies": change("cookies"),
        "before_consent_domains": change("before_consent_domains"),
    }
