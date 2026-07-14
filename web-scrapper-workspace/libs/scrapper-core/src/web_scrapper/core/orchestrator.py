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
    """Push one queue item per crawl URL. Returns number of pages enqueued."""
    links = fetch_crawl_links(settings.api_base_url, crawl_job_id)
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
