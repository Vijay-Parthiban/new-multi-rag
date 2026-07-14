import logging
from uuid import UUID

from rq import Queue

from crawler_shared.config import get_settings
from crawler_shared.redis.client import get_redis_connection

logger = logging.getLogger(__name__)

CRAWL_QUEUE_NAME = "crawl"
SCRAPE_QUEUE_NAME = "scrape"
SCRAPE_PAGE_QUEUE_NAME = "scrape-page"


def get_crawl_queue() -> Queue:
    settings = get_settings()
    return Queue(CRAWL_QUEUE_NAME, connection=get_redis_connection(), default_timeout=settings.rq_default_timeout)


def get_scrape_queue() -> Queue:
    settings = get_settings()
    return Queue(SCRAPE_QUEUE_NAME, connection=get_redis_connection(), default_timeout=settings.rq_default_timeout)


def get_scrape_page_queue() -> Queue:
    settings = get_settings()
    return Queue(
        SCRAPE_PAGE_QUEUE_NAME,
        connection=get_redis_connection(),
        default_timeout=settings.rq_default_timeout,
    )


def enqueue_crawl(job_id: UUID | str, task_path: str = "worker.tasks.run_crawl_job") -> None:
    """Enqueue a crawl job for asynchronous processing by the worker."""
    queue = get_crawl_queue()
    queue.enqueue(task_path, str(job_id))
    logger.info("enqueue_crawl job_id=%s queue=%s task=%s", str(job_id), CRAWL_QUEUE_NAME, task_path)


def enqueue_crawl_and_scrape(
    crawl_job_id: UUID | str,
    scrape_job_id: UUID | str,
    task_path: str = "worker.tasks.run_crawl_and_scrape_job",
) -> None:
    """Enqueue a combined crawl-then-scrape pipeline."""
    queue = get_crawl_queue()
    queue.enqueue(task_path, str(crawl_job_id), str(scrape_job_id))
    logger.info(
        "enqueue_crawl_and_scrape crawl_job_id=%s scrape_job_id=%s queue=%s task=%s",
        str(crawl_job_id),
        str(scrape_job_id),
        CRAWL_QUEUE_NAME,
        task_path,
    )


def enqueue_scrape(job_id: UUID | str, task_path: str = "worker.tasks.run_scrape_job") -> None:
    """Enqueue scrape orchestrator (fans out one task per URL)."""
    queue = get_scrape_queue()
    queue.enqueue(task_path, str(job_id))
    logger.info("enqueue_scrape job_id=%s queue=%s task=%s", str(job_id), SCRAPE_QUEUE_NAME, task_path)


def enqueue_scrape_page(
    *,
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: str,
    url: str,
    index: int,
    depth: int,
    parent: str | None,
    stem: str,
    attempt: int = 0,
    task_path: str = "worker.tasks.run_scrape_page",
) -> None:
    """Enqueue a single page scrape (processed in parallel by scrape-page workers)."""
    queue = get_scrape_page_queue()
    queue.enqueue(
        task_path,
        scrape_job_id,
        crawl_job_id,
        embedding_source,
        url,
        index,
        depth,
        parent,
        stem,
        attempt,
    )
    logger.info(
        "enqueue_scrape_page scrape_job_id=%s index=%d url=%s attempt=%d queue=%s",
        scrape_job_id,
        index,
        url,
        attempt,
        SCRAPE_PAGE_QUEUE_NAME,
    )


def enqueue_scrape_finalize(
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: str,
    task_path: str = "worker.tasks.run_scrape_finalize",
) -> None:
    """Persist artifacts to disk and mark scrape job completed."""
    queue = get_scrape_queue()
    queue.enqueue(task_path, scrape_job_id, crawl_job_id, embedding_source)
    logger.info("enqueue_scrape_finalize scrape_job_id=%s queue=%s", scrape_job_id, SCRAPE_QUEUE_NAME)
