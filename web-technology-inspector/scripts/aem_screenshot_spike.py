"""Check that Page Properties screenshots work with your AEM author.

Opens the page's Page Properties in a browser with your AEM Local
Development Token, finds the fields containing --term, and saves a
screenshot of each with the field highlighted, under data/screenshots/.
Read-only: write requests are blocked in the browser, the token goes only
to your author, and nothing is clicked except dialog tabs.

Usage (from the web-technology-inspector folder):
  python scripts/aem_screenshot_spike.py \\
      --author https://author-pXXXX-eYYYY.adobeaemcloud.com \\
      --page /content/your-site/us/en/home --term tracking.your-vendor.com [--show-browser]
"""

import argparse
import getpass
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web_inspector.aem_screens import AemLoginRequired, capture_page_properties  # noqa: E402
from web_inspector.site_config import valid_author  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--author", required=True, help="AEM author origin")
    parser.add_argument("--page", required=True, help="content path of the page, e.g. /content/site/us/en/home")
    parser.add_argument("--term", required=True, help="value to find in the page's properties")
    parser.add_argument("--show-browser", action="store_true", help="open a visible browser window")
    args = parser.parse_args()

    if not valid_author(args.author) or not args.page.startswith("/content/"):
        sys.exit("--author must be an https origin and --page a path under /content/.")
    token = os.environ.get("AEM_TOKEN", "").strip() or getpass.getpass(
        "AEM Local Development Token (input hidden): ").strip()
    if not token:
        sys.exit("No AEM token given.")

    try:
        result = capture_page_properties(args.author, args.page, args.term, token,
                                          show_browser=args.show_browser)
    except AemLoginRequired as exc:
        sys.exit(f"{exc}.\nThe token works for data calls but not for author UI pages on this "
                 "environment; tell Claude, so the app can use a one-time browser sign-in instead.")

    folder = ROOT / "data" / "screenshots" / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Opened {result['url']}")
    print(f"Write requests blocked: {len(result['blocked_writes'])}")
    for request in result["blocked_writes"][:5]:
        print("  ", request[:120])
    if not result["fields"]:
        (folder / "page-properties.png").write_bytes(result["page_image"])
        print(f"No field contains '{args.term}'. Screenshot of the dialog: {folder / 'page-properties.png'}")
        return
    for index, field in enumerate(result["fields"], 1):
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", field["name"] or field["label"] or "field").strip("-")
        path = folder / f"{index:02d}-{name}.png"
        path.write_bytes(field["image"])
        print(f"Field '{field['label'] or field['name']}' = {field['value'][:80]}\n   -> {path}")


if __name__ == "__main__":
    main()
