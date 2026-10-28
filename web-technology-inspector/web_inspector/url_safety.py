"""Only scan approved, public websites.

The browser is pointed at URLs typed into the app; restricting it to the
configured website domains, resolved to public addresses, keeps the
scanner from being aimed at internal services.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

PRIVATE = ("localhost", "localhost.localdomain")


def validate_public_url(url: str, allowed_hosts: set[str]) -> str:
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
