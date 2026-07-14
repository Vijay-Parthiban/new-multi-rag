import httpx

from crawler_shared.types import ScrapedPage
from web_scrapper.utils.html import extract_text, extract_title


class PageExtractor:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(headers={"User-Agent": "web-scrapper/0.1"})
        self._owns_client = client is None

    def scrape(self, url: str) -> ScrapedPage:
        response = self._client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        html = response.text
        return ScrapedPage(
            url=str(response.url),
            title=extract_title(html),
            text=extract_text(html),
            html=html,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
