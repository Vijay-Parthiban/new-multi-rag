import logging
from typing import Any

import httpx

from src.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


async def start_crawl_scrape_pipeline(
    *,
    seed_url: str,
    max_depth: int,
    max_pages: int,
    mode: str,
    embedding_source: str,
    qdrant_collection: str,
    embedding_model: str,
    sparse_embedding_model: str | None,
    pipeline_description: str,
    use_sparse: bool,
) -> dict[str, Any]:
    """Call web-scrapper with per-pipeline Qdrant + embedding configuration."""
    settings = get_settings()
    url = f"{settings.scraper_api_url.rstrip('/')}/pipelines/crawl-scrape"
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
        headers = {}
        key = settings.scraper_api_key or settings.api_key
        if key:
            headers["X-API-Key"] = key
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(
            "scraper_pipeline_started collection=%s model=%s seed=%s",
            qdrant_collection,
            embedding_model,
            seed_url,
        )
        return data
