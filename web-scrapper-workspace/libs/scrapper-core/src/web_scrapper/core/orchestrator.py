import logging
import uuid

from crawler_shared.config import Settings
from crawler_shared.redis.queue import enqueue_scrape_page
from crawler_shared.redis.scrape_coordinator import init_scrape_job
from crawler_shared.types import EmbeddingSource

from web_scrapper.clients.crawl_links import fetch_crawl_links
from web_scrapper.core.page_task import stem_for_index

logger = logging.getLogger(__name__)


def enqueue_scrape_pages(
    settings: Settings,
    *,
    scrape_job_id: uuid.UUID,
    crawl_job_id: uuid.UUID,
    embedding_source: EmbeddingSource,
) -> int:
    """
    Distributes discrete page scraping tasks to Redis queues by fetching all discovered 
    links from the original crawl job. 
    
    This splits a monolithic scrape sweep into granular, retryable worker tasks for 
    parallel processing.

    Args:
        settings: Application settings.
        scrape_job_id: ID of the overarching scrape job tracking the batch.
        crawl_job_id: ID of the antecedent crawl job that discovered the links.
        embedding_source: Modality target (e.g., 'markdown' or 'image').

    Returns:
        The total number of page-level tasks enqueued.
    """
    links = fetch_crawl_links(
        settings.api_base_url,
        crawl_job_id,
        api_key=settings.api_key or None,
    )
    job_id = str(scrape_job_id)
    init_scrape_job(job_id, total_pages=len(links))

    for index, link in enumerate(links):
        stem = stem_for_index(index, link.url)
        enqueue_scrape_page(
            scrape_job_id=job_id,
            crawl_job_id=str(crawl_job_id),
            embedding_source=embedding_source,
            url=link.url,
            index=index,
            depth=link.depth,
            parent=link.parent,
            stem=stem,
            attempt=0,
        )

    logger.info(
        "scrape_pages_enqueued scrape_job_id=%s crawl_job_id=%s count=%d",
        job_id,
        crawl_job_id,
        len(links),
    )
    return len(links)
