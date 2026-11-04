"""Technologies people named themselves, for domains the built-in signatures
don't know (e.g. a regional vendor or a site's own tracking endpoint).

Stored per machine as JSON next to the scan history, owner-only, and used by
every later scan: a labelled domain and its subdomains match like a built-in
host signature. Built-in signatures still win where both match.
"""

from __future__ import annotations

import json
import os
import tempfile

from .config import settings
from .site_config import DOMAIN
from .utils import harden_file_permissions

FILE_NAME = "custom_signatures.json"
MAX_NAME = 60
OTHER_CATEGORY = "Other"


def _path():
    return settings.data_path / FILE_NAME


def load() -> list[dict]:
    """[{"domain", "name", "category"}], sorted by domain; [] if none or unreadable."""
    try:
        values = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    return sorted(
        (v for v in values
         if isinstance(v, dict) and all(isinstance(v.get(k), str) and v[k] for k in ("domain", "name", "category"))),
        key=lambda v: v["domain"],
    )


def version() -> tuple:
    """Changes whenever the file does, so callers can cache what they built
    from it. Every save replaces the file, so its inode changes too, even
    within one clock tick."""
    path = _path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path),)
    return (str(path), stat.st_ino, stat.st_mtime_ns, stat.st_size)


def clean(domain: str, name: str, category: str) -> tuple[dict, list[str]]:
    """Normalise a label form; (values, errors), values usable only without errors."""
    domain = (domain or "").strip().lower().lstrip(".").rstrip(".")
    name = " ".join((name or "").split())
    category = (category or "").strip() or OTHER_CATEGORY
    errors = []
    if not DOMAIN.match(domain):
        errors.append("Domain: enter a host name like tags.vendor.com.")
    if not name:
        errors.append("Name: enter what this domain is, e.g. the vendor or product.")
    elif len(name) > MAX_NAME:
        errors.append(f"Name: at most {MAX_NAME} characters.")
    return {"domain": domain, "name": name, "category": category}, errors


def _write(values: list[dict]) -> None:
    directory = settings.data_path
    directory.mkdir(parents=True, exist_ok=True)
    harden_file_permissions(directory, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".custom_signatures.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(values, handle, indent=2)
    os.replace(temporary, _path())
    harden_file_permissions(_path())


def save(domain: str, name: str, category: str) -> dict:
    """Add or replace the label for a domain; raises ValueError if invalid."""
    values, errors = clean(domain, name, category)
    if errors:
        raise ValueError(" ".join(errors))
    _write([v for v in load() if v["domain"] != values["domain"]] + [values])
    return values


def delete(domain: str) -> None:
    domain = (domain or "").strip().lower()
    _write([v for v in load() if v["domain"] != domain])
