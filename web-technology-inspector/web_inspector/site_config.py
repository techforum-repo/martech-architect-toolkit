"""Local AEM configuration management.

Creates missing configuration files automatically.
Existing configurations are never overwritten.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlsplit

BASE = Path(__file__).resolve().parent.parent / "config"

CONFIG_FILES = {
    "aem_environments.json": "environments",
    "aem_mappings.json": "mappings",
}


def initialize():
    BASE.mkdir(parents=True, exist_ok=True)

    for filename, key in CONFIG_FILES.items():
        path = BASE / filename

        if not path.exists():
            path.write_text(
                json.dumps({key: []}, indent=2),
                encoding="utf-8"
            )


def _validate_name(name, key):
    if CONFIG_FILES.get(name) != key:
        raise ValueError(
            "Unsupported configuration file or key"
        )


def load(name, key):
    _validate_name(name, key)
    initialize()

    path = BASE / name

    data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    values = data.get(key)

    if not isinstance(values, list):
        raise ValueError(
            "Invalid configuration format: " + name
        )

    return values


def save(name, key, values):
    _validate_name(name, key)
    initialize()

    if not isinstance(values, list):
        raise ValueError(
            "Configuration values must be a list"
        )

    path = BASE / name
    temporary = path.with_suffix(".tmp")

    temporary.write_text(
        json.dumps({key: values}, indent=2),
        encoding="utf-8"
    )

    temporary.replace(path)


def valid_author(url):
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path in ("", "/")
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def parse_domains(text):
    """Comma- or line-separated domains as a sorted list, or None if any is invalid.

    Used for a mapping's extra first-party domains (e.g. a site's own CDN).
    """

    domains = {
        part.strip().lower().lstrip(".")
        for part in re.split(r"[,\s]+", text or "")
        if part.strip()
    }

    if any(not DOMAIN.match(domain) for domain in domains):
        return None

    return sorted(domains)


def clean_mapping(name, domain, prefix, root):
    """Normalise a website mapping form and explain anything still wrong.

    Accepts what people paste: a full URL or "host/" in the domain field,
    a prefix without its leading slash, stray spaces. Returns
    (values, errors); values are only usable when errors is empty.
    """

    errors = []
    name = (name or "").strip()
    domain = (domain or "").strip().lower()
    prefix = (prefix or "").strip()
    root = (root or "").strip().rstrip("/")

    if "://" in domain or "/" in domain or "@" in domain:
        try:
            parsed = urlsplit(domain if "://" in domain else "https://" + domain)
            if parsed.username or parsed.password:
                errors.append("Published domain: leave out user names and passwords (use Basic Authentication below).")
            if parsed.port not in (None, 443):
                errors.append("Published domain: only the standard HTTPS port is supported.")
            domain = parsed.hostname or ""
        except ValueError:
            domain = ""
    elif ":" in domain:
        errors.append("Published domain: only the standard HTTPS port is supported.")
        domain = domain.split(":", 1)[0]

    prefix = "/" + prefix.lstrip("/")
    prefix = prefix.rstrip("/") or "/"

    if not name:
        errors.append("Website name: enter a name.")
    if not DOMAIN.match(domain):
        errors.append("Published domain: enter a host name like www.example.com.")
    if any(part in (".", "..") for part in prefix.split("/")) or " " in prefix:
        errors.append("Published URL prefix: use a path like /us/en, or / for the whole site.")
    if not root.startswith("/content/") or any(part in (".", "..") for part in root.split("/")):
        errors.append("AEM content root: enter a path under /content/, like /content/site/us/en.")

    return {
        "name": name,
        "published_domain": domain,
        "published_prefix": prefix,
        "content_root": root,
    }, errors


def match(url, mappings):
    try:
        parsed = urlparse(url)

        if parsed.scheme != "https" or not parsed.hostname:
            return None

        candidates = []

        for mapping in mappings:
            prefix = (
                mapping["published_prefix"].rstrip("/")
                or "/"
            )

            path = parsed.path or "/"

            if (
                parsed.hostname.lower()
                != mapping["published_domain"].lower()
            ):
                continue

            if (
                prefix == "/"
                or path == prefix
                or path.startswith(prefix + "/")
            ):
                candidates.append(
                    (len(prefix), mapping)
                )

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda item: item[0]
        )[1]

    except (ValueError, KeyError, TypeError):
        return None
