# Web Technology Inspector

A Streamlit app that loads a web page in a real browser, records what it
loads and why, and ties what it finds back to Adobe Experience Manager.

For one page it answers:

- **Which marketing and analytics technologies run here?** Adobe Web SDK,
  Analytics, Target, ECID, Tags, Google, Meta, consent tools and more,
  detected from requests and from the libraries that actually ran on the page.
- **What does each third party cost?** Requests, bytes transferred and time per domain.
- **What fires before consent?** Optionally accepts the consent banner during
  the scan and splits requests and cookies into before / after consent.
- **How was this script added?** The browser's initiator chain: page HTML,
  inline code, a tag manager, or another script.
- **Where is it in AEM?** The AEM page behind the URL, and every node under
  `/content`, `/conf` and `/apps` on author that references the script or domain.
- **What changed since last time?** Every scan is kept, and any two scans of a
  page can be compared.

Requires Python 3.11 or 3.12.

## Start

```bash
./start-unix.sh          # Linux / macOS
start-windows.bat        # Windows
```

The start script creates a virtual environment, installs dependencies and the
Chromium browser used for scans, copies `.env.example` to `.env`, and opens the
app on the first free port from 8502.

The app starts in **mock mode**: a sample scan and sample AEM data, so every
page can be tried without a website or AEM token. Turn it off in the sidebar,
or set `MOCK_MODE=false` in `.env`.

## Set up for your sites

On the **Settings** page:

1. Add an **AEM environment**: a name and the author URL, for example
   `https://author-p12345-e67890.adobeaemcloud.com`.
2. Add a **website mapping**: the published domain, the URL prefix and the
   content root it maps to (for example `/us/en` → `/content/site/us/en`).
   Only domains with a mapping can be scanned.
3. Add your AEM **Local Development Token** for the environment, kept for the
   session only or encrypted on this machine (key in the OS credential store).

## How AEM lookups work

All AEM access is read-only `GET` requests, checked in `web_inspector/aem_client.py`
before anything is sent:

| Step | Request |
|---|---|
| Find the page | Prefix mapping, then `<path>/jcr:content.json` (one node) to confirm it exists |
| Vanity URLs | QueryBuilder search on `sling:vanityPath` when the mapping misses |
| References | QueryBuilder full-text search under `/content`, `/conf` and `/apps` |

QueryBuilder calls may only use an allowlist of 8 parameters, only under those
three roots, and return at most 100 results. Redirects are never followed with
a token.

Full-text search doesn't cover code files under `/apps`. When the `/apps`
search finds nothing, the app suggests the **Find Text References** script in
the AEM Groovy Runner (`../aem-groovy-runner`), with the `/apps/<project>`
folder taken from the page's `/etc.clientlibs/<project>/` URLs. That script
reads clientlib JavaScript, HTL and CSS directly, read-only.

`scripts/aem_spike.py` runs these lookups for one URL from the command line,
which is a quick way to check what your AEM user may call:

```bash
.venv/bin/python scripts/aem_spike.py https://www.your-site.com/us/en/page.html \
    --author https://author-pXXXX-eYYYY.adobeaemcloud.com \
    --prefix /us/en --root /content/your-site/us/en --term tracking.your-vendor.com
```

## Scanning notes

- **Bot protection.** Sites behind Akamai, Cloudflare and similar often block
  the hidden (headless) browser; the app says so. Tick **Show browser** to scan
  with a visible window, which is usually allowed.
- **Consent.** Recognised banners: OneTrust, Cookiebot, TrustArc, Didomi,
  Usercentrics, Quantcast and Sourcepoint. If none is found, the scan says that
  nothing was accepted. Consent tools and tag managers loading before consent
  are marked as expected; other third parties are flagged for review.
- **First party.** A domain counts as first party when it is the page's domain
  or a subdomain of it, or is listed under **Also first party** on the website
  mapping (for a site's own CDN on a different domain).
- **Timing.** The scan scrolls the page and waits for the network to settle
  (`SETTLE_SECONDS`). Tags that fire later, or only on clicks, are not captured.

## Local data

| Path | Contents |
|---|---|
| `config/` | AEM environments and website mappings (JSON, not committed) |
| `data/inspector.db` | Scan history: technologies, domains, cookie names, consent findings. Never cookie values, inline code or screenshots |
| `logs/` | Rotating application log |

Files are restricted to your user on Linux and macOS.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m pyflakes web_inspector tests scripts app.py
```

`tests/test_scanner.py` runs the real scanner in Chromium against fixture pages
served through Playwright routing, so it needs no network.

`scripts/audit_public_repo.py` is a basic pre-publish check for private URLs,
tokens and keys in tracked files.

## Limitations

- Tag-manager attribution comes from the browser's initiator chain; the exact
  tag or rule is not identified.
- An AEM reference shows where a value is stored, not proof that it caused a request.
- Full-text search depends on the AEM search index; code under `/apps` may not be indexed.
- Use only on websites and AEM environments you are authorised to inspect.
