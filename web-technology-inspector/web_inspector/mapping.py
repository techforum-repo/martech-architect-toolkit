"""Map a published URL to its AEM content path using a website mapping."""

from urllib.parse import urlparse, quote


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

    path = parsed.path or "/"

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

    if suffix.endswith(".html"):
        suffix = suffix[:-5]

    if any(
        part in (".", "..")
        for part in suffix.split("/")
    ):
        raise ValueError("Invalid content path")

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
