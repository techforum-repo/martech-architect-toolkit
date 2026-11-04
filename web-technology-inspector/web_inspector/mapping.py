"""Map a published URL to its AEM content path using a website mapping."""

from urllib.parse import urlparse, quote


def sling_resource_path(path):
    """The page part of a published URL path, as Sling reads it: the first
    segment with a dot ends it; the rest of that segment is selectors and
    extension (page.mobile.html) and what follows is a suffix. So
    /us/en.html is /us/en, and page.infinity.json/x never reaches AEM as
    part of a page path (it would read the whole tree, not one node)."""
    segments = (path or "/").split("/")
    if any(part in (".", "..") for part in segments):
        raise ValueError("Invalid content path")
    for index, segment in enumerate(segments):
        if "." in segment:
            segments = segments[:index] + [segment.split(".", 1)[0]]
            break
    return "/".join(segments).rstrip("/") or "/"


def resolve(url, mapping, environment):
    parsed = urlparse(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(
            "Published URL must be HTTPS"
        )

    if (
        parsed.hostname.lower()
        != mapping["published_domain"].lower()
    ):
        raise ValueError(
            "Published domain does not match mapping"
        )

    prefix = (
        mapping["published_prefix"].rstrip("/")
        or "/"
    )

    path = sling_resource_path(parsed.path)

    if (
        prefix != "/"
        and path != prefix
        and not path.startswith(prefix + "/")
    ):
        raise ValueError(
            "Published path does not match mapping"
        )

    suffix = (
        path[len(prefix):]
        if prefix != "/"
        else path
    ).rstrip("/")

    content = (
        mapping["content_root"].rstrip("/")
        + (
            "/" + suffix.lstrip("/")
            if suffix
            else ""
        )
    )

    author = environment["author_base"].rstrip("/")

    if (
        urlparse(author).scheme != "https"
        or not urlparse(author).hostname
    ):
        raise ValueError(
            "AEM Author URL must be HTTPS"
        )

    encoded = quote(content, safe="/")

    return {
        "content_path": content,
        "editor_url": (
            author
            + "/editor.html"
            + encoded
            + ".html"
        ),
    }
