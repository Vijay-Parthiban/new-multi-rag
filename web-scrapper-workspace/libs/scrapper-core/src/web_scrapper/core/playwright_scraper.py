import logging
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError

from crawler_shared.playwright_browser import safe_browser_page
from crawler_shared.playwright_config import PAGE_GOTO_WAIT_UNTIL
from web_scrapper.utils.markdown import html_to_markdown_content

logger = logging.getLogger(__name__)


@dataclass
class PlaywrightScrapeResult:
    url: str
    title: str | None
    html: str
    markdown: str
    screenshot_bytes: bytes


class PlaywrightPageScraper:
    """Scrape one page inside a short-lived stealth browser (full cleanup after each URL)."""

    def __init__(self, *, timeout_ms: int = 30000) -> None:
        self._timeout_ms = timeout_ms

    async def scrape(self, url: str) -> PlaywrightScrapeResult:
        try:
            async with safe_browser_page() as page:
                response = await page.goto(
                    url,
                    wait_until=PAGE_GOTO_WAIT_UNTIL,
                    timeout=self._timeout_ms,
                )

                await page.wait_for_selector("body", state="attached", timeout=15000)

                final_url = response.url if response is not None else page.url
                title = await page.title() or None

                screenshot_bytes = await page.screenshot(
                    full_page=True,
                    type="png",
                    timeout=15000,
                    animations="disabled",
                )

                html = await page.content()
                markdown = html_to_markdown_content(html, title=title)

                return PlaywrightScrapeResult(
                    url=final_url,
                    title=title,
                    html=html,
                    markdown=markdown,
                    screenshot_bytes=screenshot_bytes,
                )
        except PlaywrightError as exc:
            logger.exception("playwright_scrape_failed url=%s error=%s", url, str(exc))
            raise
