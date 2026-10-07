import logging
from typing import Any

import httpx

from src.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


def scraper_base_url() -> str:
    return get_settings().scraper_api_url.rstrip("/")


def _headers() -> dict[str, str]:
    settings = get_settings()
    key = settings.scraper_api_key or settings.api_key
    return {"X-API-Key": key} if key else {}


def _log_failure(operation: str, url: str, exc: httpx.HTTPError) -> None:
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    logger.error("scraper_request_failed operation=%s url=%s status=%s error=%s", operation, url, status, exc)


async def check_scraper_health() -> str:
    """Return the base URL when the scraper answers. Raise when it does not.

    A scrape job calls the scraper once per seed. One probe up front turns a dead service
    into one clear row error instead of one connection error per URL.
    """
    url = f"{scraper_base_url()}/health"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("check_scraper_health", url, exc)
            raise
    return scraper_base_url()


async def start_crawl_scrape_pipeline(
    *,
    seed_url: str,
    max_depth: int,
    max_pages: int,
    mode: str,
    embedding_source: str,
    qdrant_collection: str | None,
    embedding_model: str | None,
    sparse_embedding_model: str | None,
    pipeline_description: str,
    use_sparse: bool,
) -> dict[str, Any]:
    """Call web-scrapper with per-pipeline Qdrant + embedding configuration.

    ``embedding_source="none"`` skips embeddings entirely: the scrape writes page
    artifacts and nothing reaches Qdrant, so the collection and model arguments are
    passed as ``None``.
    """
    url = f"{scraper_base_url()}/pipelines/crawl-scrape"
    payload = {
        "seed_url": seed_url,
        "max_depth": max_depth,
        "max_pages": max_pages,
        "mode": mode,
        "embedding_source": embedding_source,
        "qdrant_collection": qdrant_collection,
        "embedding_model": embedding_model,
        "sparse_embedding_model": sparse_embedding_model,
        "pipeline_description": pipeline_description,
        "use_sparse": use_sparse,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("start_crawl_scrape_pipeline", url, exc)
            raise
        data = response.json()
        logger.info(
            "scraper_pipeline_started collection=%s model=%s seed=%s",
            qdrant_collection,
            embedding_model,
            seed_url,
        )
        return data


async def get_scrape_job(scrape_job_id: str) -> dict[str, Any]:
    """Read one scrape job, for polling its status."""
    url = f"{scraper_base_url()}/scrapes/{scrape_job_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("get_scrape_job", url, exc)
            raise
        return response.json()


async def get_scrape_pages(scrape_job_id: str) -> dict[str, Any]:
    """Read the page list of a finished scrape job."""
    url = f"{scraper_base_url()}/scrapes/{scrape_job_id}/pages"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("get_scrape_pages", url, exc)
            raise
        return response.json()


async def get_scrape_page_markdown(scrape_job_id: str, index: int) -> str:
    """Download one crawled page as Markdown text."""
    url = f"{scraper_base_url()}/scrapes/{scrape_job_id}/pages/{index}/markdown"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("get_scrape_page_markdown", url, exc)
            raise
        return response.text


async def get_scrape_page_screenshot(scrape_job_id: str, index: int) -> bytes:
    """Download the full-page screenshot of one crawled page as PNG bytes."""
    url = f"{scraper_base_url()}/scrapes/{scrape_job_id}/pages/{index}/screenshot"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _log_failure("get_scrape_page_screenshot", url, exc)
            raise
        return response.content
