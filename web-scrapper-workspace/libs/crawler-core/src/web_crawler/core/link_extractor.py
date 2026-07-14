from __future__ import annotations

import logging
import httpx
from itertools import cycle
from typing import Literal

from crawler_shared.playwright_browser import fetch_html_sync
from crawler_shared.playwright_config import DEFAULT_VIEWPORTS
from web_crawler.utils.url import extract_links, is_http_url, normalize_url

logger = logging.getLogger(__name__)

FetchMode = Literal["httpx", "playwright", "auto"]


class LinkExtractor:
    def __init__(
        self,
        client: httpx.Client,
        *,
        fetch_mode: FetchMode = "httpx",
        playwright_timeout_ms: int = 15000,
    ) -> None:
        """Fetch HTML pages and extract outgoing links.

        `fetch_mode` controls how pages are retrieved:
        - `httpx`: HTTP only
        - `playwright`: browser only (requires playwright installed + browser available)
        - `auto`: HTTP first, fall back to playwright when the HTML looks like a JS shell
        """
        self._client = client
        self._fetch_mode = fetch_mode
        self._playwright_timeout_ms = playwright_timeout_ms
        self._viewport_cycle = cycle(DEFAULT_VIEWPORTS)

    def fetch(self, url: str) -> tuple[str | None, int | None]:
        """Fetch a URL and return (html, status_code).

        For non-HTML responses, returns (None, status_code).
        """
        if self._fetch_mode == "playwright":
            return self._fetch_with_playwright(url)

        html, status_code = self._fetch_with_httpx(url)
        if self._fetch_mode == "httpx":
            return html, status_code

        if html is None:
            return None, status_code
        if not self._looks_like_js_shell(html):
            return html, status_code

        rendered_html, rendered_status = self._fetch_with_playwright(url)
        if rendered_html is None:
            return html, status_code
        return rendered_html, rendered_status

    def _fetch_with_httpx(self, url: str) -> tuple[str | None, int | None]:
        try:
            response = self._client.get(url, follow_redirects=True, timeout=15.0)
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type.lower():
                return None, response.status_code
            return response.text, response.status_code
        except httpx.HTTPError:
            return None, None

    def _fetch_with_playwright(self, url: str) -> tuple[str | None, int | None]:
        try:
            return fetch_html_sync(
                url,
                timeout_ms=self._playwright_timeout_ms,
                viewport=next(self._viewport_cycle),
            )
        except ImportError:
            return None, None

    def close(self) -> None:
        """No persistent Playwright resources; kept for API compatibility with CrawlerEngine."""
        return None

    def extract(self, html: str, base_url: str) -> list[str]:
        """Extract outgoing normalized http(s) links from HTML."""
        return extract_links(html, base_url)

    @staticmethod
    def normalize(url: str) -> str:
        normalized = normalize_url(url)
        if not is_http_url(normalized):
            raise ValueError(f"Unsupported URL scheme: {url}")
        return normalized

    @staticmethod
    def _looks_like_js_shell(html: str) -> bool:
        lowered = html.lower()
        has_script = "<script" in lowered
        has_anchor = "<a " in lowered
        has_app_shell_marker = any(
            marker in lowered
            for marker in ('id="root"', "id='root'", 'id="app"', "id='app'", "__next_data__")
        )
        return has_script and (not has_anchor or has_app_shell_marker)
