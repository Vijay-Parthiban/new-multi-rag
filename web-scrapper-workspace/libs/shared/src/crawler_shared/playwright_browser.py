"""Shared Playwright lifecycle helpers — launch, use, always tear down."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from crawler_shared.playwright_config import (
    CHROMIUM_LAUNCH_ARGS,
    PAGE_GOTO_WAIT_UNTIL,
    stealth_async,
    stealth_context_options,
    stealth_sync,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def safe_browser_page(
    *,
    viewport: dict[str, int] | None = None,
) -> AsyncIterator[Any]:
    """Launch a stealth Chromium page and always close page, context, browser, and driver."""
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=CHROMIUM_LAUNCH_ARGS)
    context = await browser.new_context(**stealth_context_options(viewport=viewport))
    page = await context.new_page()
    await stealth_async(page)

    logger.debug("playwright_async_page_ready")
    try:
        yield page
    except Exception:
        logger.exception("playwright_async_page_error")
        raise
    finally:
        await page.close()
        await context.close()
        await browser.close()
        await playwright.stop()
        logger.debug("playwright_async_resources_closed")


@contextmanager
def safe_sync_browser_page(
    *,
    viewport: dict[str, int] | None = None,
) -> Iterator[Any]:
    """Sync variant: launch a stealth page and always tear down all Playwright resources."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True, args=CHROMIUM_LAUNCH_ARGS)
    context = browser.new_context(**stealth_context_options(viewport=viewport))
    page = context.new_page()
    stealth_sync(page)

    logger.debug("playwright_sync_page_ready")
    try:
        yield page
    except Exception:
        logger.exception("playwright_sync_page_error")
        raise
    finally:
        page.close()
        context.close()
        browser.close()
        playwright.stop()
        logger.debug("playwright_sync_resources_closed")


async def fetch_html_async(url: str, *, timeout_ms: int = 15000) -> tuple[str | None, int | None]:
    """Fetch HTML via a short-lived stealth browser page."""
    from playwright.async_api import Error as PlaywrightError

    try:
        async with safe_browser_page() as page:
            response = await page.goto(
                url,
                wait_until=PAGE_GOTO_WAIT_UNTIL,
                timeout=timeout_ms,
            )
            await page.wait_for_selector("body", state="attached", timeout=timeout_ms)
            status_code = response.status if response is not None else None
            return await page.content(), status_code
    except PlaywrightError:
        return None, None


def fetch_html_sync(
    url: str,
    *,
    timeout_ms: int = 15000,
    viewport: dict[str, int] | None = None,
) -> tuple[str | None, int | None]:
    """Fetch HTML via a short-lived stealth browser page (sync)."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        with safe_sync_browser_page(viewport=viewport) as page:
            response = page.goto(
                url,
                wait_until=PAGE_GOTO_WAIT_UNTIL,
                timeout=timeout_ms,
            )
            page.wait_for_selector("body", state="attached", timeout=timeout_ms)
            status_code = response.status if response is not None else None
            return page.content(), status_code
    except PlaywrightError:
        return None, None
