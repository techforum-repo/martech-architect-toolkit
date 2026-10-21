"""Read-only published-page screenshot capture."""

from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def capture_screenshot(url, expected_domain):
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_domain
    ):
        raise ValueError(
            "Screenshot URL must match the configured "
            "HTTPS website domain."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        try:
            context = browser.new_context(
                viewport={
                    "width": 1440,
                    "height": 900
                },
                device_scale_factor=1,
                service_workers="block",
                accept_downloads=False
            )

            page = context.new_page()

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(2000)

            final_url = urlparse(page.url)

            if (
                final_url.scheme != "https"
                or final_url.hostname != expected_domain
            ):
                raise ValueError(
                    "Page redirected outside the "
                    "configured website domain."
                )

            screenshot = page.screenshot(
                full_page=False,
                animations="disabled"
            )

            return {
                "image": screenshot,
                "title": page.title(),
                "url": page.url
            }

        finally:
            browser.close()
