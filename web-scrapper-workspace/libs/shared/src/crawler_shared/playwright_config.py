"""Shared Playwright launch and stealth settings for crawl and scrape workers."""

from typing import TYPE_CHECKING

from playwright_stealth import Stealth

if TYPE_CHECKING:
    from playwright.async_api import Page as AsyncPage
    from playwright.sync_api import Page as SyncPage

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

CHROMIUM_LAUNCH_ARGS: list[str] = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

DEFAULT_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
]

PAGE_GOTO_WAIT_UNTIL = "domcontentloaded"

_stealth = Stealth(
    navigator_languages_override=("en-US", "en"),
    navigator_user_agent_override=DESKTOP_USER_AGENT,
)


async def stealth_async(page: "AsyncPage") -> None:
    """Apply playwright-stealth evasions to a page before navigation."""
    await _stealth.apply_stealth_async(page)


def stealth_sync(page: "SyncPage") -> None:
    """Apply playwright-stealth evasions to a page before navigation."""
    _stealth.apply_stealth_sync(page)


def stealth_context_options(*, viewport: dict[str, int] | None = None) -> dict[str, object]:
    return {
        "user_agent": DESKTOP_USER_AGENT,
        "locale": "en-US",
        "viewport": viewport or DEFAULT_VIEWPORTS[-1],
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        },
    }
