"""Playwright browser scanner with CDP initiator evidence."""

from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def scan(url):
    parsed = urlparse(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("A valid HTTPS URL is required")

    requests = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        try:
            context = browser.new_context(
                service_workers="block",
                accept_downloads=False
            )

            page = context.new_page()
            cdp = context.new_cdp_session(page)

            cdp.send("Network.enable")

            def on_request(event):
                request = event.get("request", {})
                initiator = event.get("initiator", {})
                stack = initiator.get("stack") or {}
                frames = stack.get("callFrames") or []

                frame_urls = [
                    f.get("url", "")
                    for f in frames
                    if f.get("url")
                ]

                request_url = request.get("url", "")

                requests[event["requestId"]] = {
                    "request_id": event["requestId"],
                    "url": request_url,
                    "domain": (
                        urlparse(request_url).hostname or ""
                    ),
                    "type": event.get("type", ""),
                    "initiator_type": initiator.get("type", ""),
                    "initiator_url": (
                        initiator.get("url")
                        or (
                            frame_urls[0]
                            if frame_urls else ""
                        )
                    ),
                    "initiator_request_id": (
                        initiator.get("requestId", "")
                    ),
                    "stack_urls": frame_urls,
                    "status": None,
                }

            def on_response(event):
                item = requests.get(
                    event.get("requestId")
                )

                if item is not None:
                    item["status"] = event.get(
                        "response", {}
                    ).get("status", None)

            cdp.on(
                "Network.requestWillBeSent",
                on_request
            )

            cdp.on(
                "Network.responseReceived",
                on_response
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(4000)

            scripts = page.locator(
                "script[src]"
            ).evaluate_all(
                "els => els.map(e => e.src)"
            )

            inline_scripts = page.locator(
                "script:not([src])"
            ).evaluate_all(
                "els => els.map(e => e.textContent || '')"
            )

            iframes = page.locator(
                "iframe[src]"
            ).evaluate_all(
                "els => els.map(e => e.src)"
            )

            return {
                "title": page.title(),
                "url": page.url,
                "requests": list(requests.values()),
                "scripts": scripts,
                "inline_scripts": inline_scripts,
                "iframes": iframes,
            }

        finally:
            browser.close()

