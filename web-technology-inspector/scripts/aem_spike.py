"""Check which read-only AEM lookups work for a published page.

Runs, for one published URL:
  1. prefix mapping to a content path (the existing approach)
  2. confirmation that the path exists on author (one node)
  3. vanity URL lookup when the path is not found
  4. reference search under /content, /conf and /apps for a value

Usage (from the web-technology-inspector folder):
  python scripts/aem_spike.py --mock https://www.example.com/us/en/products.html --term tracking.example.com

  python scripts/aem_spike.py https://www.your-site.com/us/en/page.html \
      --author https://author-pXXXX-eYYYY.adobeaemcloud.com \
      --prefix /us/en --root /content/your-site/us/en --term tracking.your-vendor.com

With --author, the mapping comes from --prefix and --root and the token is
asked for without echoing (or read from AEM_TOKEN). Without --author, the
mappings, environments and saved token from Global AEM Settings are used.
Nothing is written to AEM: every request is a validated GET.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web_inspector import aem_lookup, aem_mock  # noqa: E402
from web_inspector.mapping import resolve  # noqa: E402
from web_inspector.site_config import load, match, valid_author  # noqa: E402


def line(label, value):
    print(f"  {label:<14} {value}")


def ask_token():
    token = os.environ.get("AEM_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("AEM Local Development Token (input hidden): ").strip()
    if not token:
        sys.exit("No AEM token given.")
    return token


def load_target(url, args):
    """Return (mapping, environment, token) or exit with a reason."""

    if args.mock:
        # The sample environment is always answered from sample data.
        return aem_mock.MAPPING, aem_mock.ENVIRONMENT, "mock-token"

    if args.author:
        if not valid_author(args.author) or not args.root:
            sys.exit("--author must be an https origin like https://author-pX-eY.adobeaemcloud.com, and --root is required.")
        environment = {"id": "cli", "name": "Command line", "author_base": args.author.rstrip("/")}
        mapping = {
            "name": "Command line",
            "published_domain": (urlsplit(url).hostname or "").lower(),
            "published_prefix": args.prefix,
            "content_root": args.root,
            "environment_id": "cli",
        }
        return mapping, environment, ask_token()

    mappings = load("aem_mappings.json", "mappings")
    # A vanity URL sits outside the mapped prefix, so fall back to any
    # mapping for the same domain to know which AEM environment to ask.
    host = (urlsplit(url).hostname or "").lower()
    mapping = match(url, mappings) or next(
        (m for m in mappings if m["published_domain"].lower() == host), None
    )
    if not mapping:
        sys.exit("No website mapping exists for this domain. Add one in Global AEM Settings.")

    environment = next(
        (e for e in load("aem_environments.json", "environments")
         if e["id"] == mapping["environment_id"]),
        None,
    )
    if not environment:
        sys.exit("The mapping's AEM environment is not configured.")

    from web_inspector.token_store import get_token
    token = os.environ.get("AEM_TOKEN", "").strip() or get_token(environment) or ""
    if not token:
        sys.exit("No AEM token. Save one in Global AEM Settings, set AEM_TOKEN, or use --author.")

    return mapping, environment, token


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="published page URL (https)")
    parser.add_argument("--term", help="domain, script URL or value to search for in AEM")
    parser.add_argument("--mock", action="store_true", help="use sample data instead of AEM")
    parser.add_argument("--author", help="AEM author origin; use with --prefix and --root instead of saved settings")
    parser.add_argument("--prefix", default="/", help="published path prefix that maps to --root (default /)")
    parser.add_argument("--root", help="content path the prefix maps to, e.g. /content/site/us/en")
    args = parser.parse_args()

    mapping, environment, token = load_target(args.url, args)
    print(f"AEM author: {environment['author_base']}{'  (mock)' if args.mock else ''}\n")

    print("1. Prefix mapping")
    try:
        content_path = resolve(args.url, mapping, environment)["content_path"]
        line("Content path", content_path)
    except ValueError as exc:
        content_path = None
        line("No match", str(exc))

    print("\n2. Confirm on author")
    if content_path is None:
        page = {"status": "not_mapped"}
        line("Skipped", "no content path to confirm")
    else:
        page = aem_lookup.verify_page(environment, content_path, token)
        line("Result", f"{page['status']} ({page['message']})")
    if page["status"] == "found":
        line("Title", page["title"])
        line("Template", page["template"])
        line("Page type", page["resource_type"])

    print("\n3. Vanity URL lookup")
    if page["status"] == "found":
        line("Skipped", "mapping confirmed")
    else:
        vanity = aem_lookup.find_vanity(environment, urlsplit(args.url).path, token)
        line("Vanity", vanity["vanity"])
        line("Result", f"{vanity['status']} ({vanity['message']})")
        for path in vanity["pages"]:
            line("Page", path)

    print("\n4. Reference search")
    if not args.term:
        line("Skipped", "pass --term to search")
    else:
        line("Term", args.term)
        for result in aem_lookup.search_references(environment, args.term, token):
            line(result["root"], f"{result['status']}, {result['total']} hit(s) ({result['message']})")
            for hit in result["hits"]:
                print(f"      {hit['node_path']}")
                if hit["resource_type"]:
                    print(f"        type: {hit['resource_type']}")


if __name__ == "__main__":
    main()
