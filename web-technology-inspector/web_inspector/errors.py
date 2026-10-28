from __future__ import annotations

"""Turn raw exceptions into a title + a short list of likely causes.

Kept framework-agnostic (no Streamlit import) so it stays unit-testable; the
UI shows the result through ui/shared.py.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FriendlyError:
    title: str
    reasons: list[str] = field(default_factory=list)
    retryable: bool = True


_BLOCKED_REASONS = [
    "The site uses bot protection (Akamai, Cloudflare or similar) that rejects automated browsers",
    "Tick “Show browser” and scan again: a visible browser window is usually allowed through",
    "If it still fails, ask the site owner to allowlist your network for scanning",
]


def friendly_error(exc: BaseException) -> FriendlyError:
    name = type(exc).__name__
    message = str(exc).strip()
    lowered = message.lower()

    if name == "ScanBlocked":
        return FriendlyError("The website blocked the automated browser", [message] + _BLOCKED_REASONS)
    if "err_http2_protocol_error" in lowered or "err_connection_reset" in lowered:
        return FriendlyError("The website dropped the connection", [
            "Bot protection often resets connections from automated browsers",
        ] + _BLOCKED_REASONS[1:])
    if "executable doesn't exist" in lowered or "playwright install" in lowered:
        return FriendlyError("The scanning browser is not installed", [
            "Run the start script again (it installs Chromium), or run: python -m playwright install chromium",
        ], retryable=False)
    if "err_name_not_resolved" in lowered or "could not be resolved" in lowered:
        return FriendlyError("The website's address could not be found", [
            "Check the URL for typos",
            "The site may only resolve on a VPN or internal network",
        ], retryable=False)
    if "approved website hostname" in lowered or "non-public" in lowered:
        return FriendlyError("This URL is not allowed for scanning", [
            "Only HTTPS URLs on a domain configured under Settings → Website Mappings can be scanned",
            "Internal and private network addresses are always rejected",
        ], retryable=False)
    if name == "TimeoutError" or "timeout" in lowered:
        return FriendlyError("The page took too long to load", [
            "The site is slow or unreachable from this machine",
            "Raise SCAN_TIMEOUT in .env if the site is just slow",
        ])
    if "err_internet_disconnected" in lowered or "err_connection_refused" in lowered:
        return FriendlyError("Could not connect to the website", [
            "Check your internet connection or VPN",
        ])

    return FriendlyError("Something went wrong", [f"{name}: {message}" if message else name])
