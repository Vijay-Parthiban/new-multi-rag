import logging
import uuid

import httpx

from crawler_shared.types import CrawlLinkRecord

logger = logging.getLogger(__name__)


def fetch_crawl_links(
    api_base_url: str,
    crawl_job_id: uuid.UUID,
    *,
    client: httpx.Client | None = None,
    page_size: int = 5000,
) -> list[CrawlLinkRecord]:
    """Load all URLs for a crawl job from the API `/crawls/{id}/links` endpoint."""
    base = api_base_url.rstrip("/")
    owns_client = client is None
    http = client or httpx.Client(timeout=60.0)
    links: list[CrawlLinkRecord] = []
    offset = 0

    try:
        while True:
            response = http.get(
                f"{base}/crawls/{crawl_job_id}/links",
                params={"limit": page_size, "offset": offset},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            for item in batch:
                links.append(
                    CrawlLinkRecord(
                        url=item["url"],
                        depth=item["depth"],
                        parent=item.get("parent"),
                        status_code=item.get("status_code"),
                    )
                )
            if len(batch) < page_size:
                break
            offset += page_size
    finally:
        if owns_client:
            http.close()

    logger.info(
        "crawl_links_fetched crawl_job_id=%s count=%d api_base_url=%s",
        crawl_job_id,
        len(links),
        base,
    )
    return links
