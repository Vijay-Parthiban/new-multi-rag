import asyncio  # <-- Added to run the async scrape function
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from crawler_db.services.crawl_service import CrawlService, ScrapeService
from crawler_db.session import session_scope
from crawler_shared.config import get_settings
from crawler_shared.logging_config import setup_logging
from crawler_shared.redis.queue import enqueue_scrape, enqueue_scrape_finalize, enqueue_scrape_page
from crawler_shared.redis.scrape_coordinator import (
    mark_page_finished,
    save_page_result,
    try_schedule_finalize,
)
from crawler_shared.storage.background_io import flush_background_writes
from crawler_shared.storage.links_file import LinksFileWriter
from web_crawler.core.engine import CrawlerEngine
from web_scrapper.core.finalize import finalize_scrape_job
from web_scrapper.core.orchestrator import enqueue_scrape_pages
from web_scrapper.core.page_task import ScrapeVectorConfig, failed_page_payload, process_scrape_page

setup_logging()
logger = logging.getLogger(__name__)


def run_crawl_job(job_id: str) -> None:
    """Worker entrypoint: execute a crawl job by ID."""
    crawl_service = CrawlService()
    settings = get_settings()
    job_uuid = uuid.UUID(job_id)

    with session_scope() as session:
        job = crawl_service.get_job(session, job_uuid)
        if job is None:
            raise ValueError(f"Crawl job not found: {job_id}")
        seed_url = job.seed_url
        max_depth = job.max_depth
        max_pages = job.max_pages
        crawl_mode = job.crawl_mode
        crawl_service.start_crawl(session, job_uuid)
        logger.info(
            "crawl_job_started id=%s seed_url=%s max_depth=%d max_pages=%d mode=%s",
            job_uuid,
            seed_url,
            max_depth,
            max_pages,
            crawl_mode,
        )

    try:
        engine = CrawlerEngine(max_depth=max_depth, max_pages=max_pages, fetch_mode=crawl_mode)
        links = engine.crawl(seed_url)
        metadata = getattr(engine, "last_metadata", {})

        writer = LinksFileWriter(settings.crawl_data_dir)
        planned_path = settings.crawl_data_dir / str(job_uuid) / "links.jsonl"

        with session_scope() as session:
            crawl_service.complete_crawl(
                session,
                job_uuid,
                links_file_path=str(planned_path.resolve()),
                total_links=len(links),
                pages_crawled=engine.pages_crawled,
                metadata=metadata,
            )

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="crawl-io") as io_pool:
            flush_background_writes(
                io_pool,
                [partial(writer.write, job_uuid, links)],
                label="crawl_links_persist",
            )

        logger.info(
            "crawl_job_completed id=%s pages_crawled=%d results=%d links_file_path=%s",
            job_uuid,
            engine.pages_crawled,
            len(links),
            str(planned_path),
        )
    except Exception as exc:
        logger.exception("crawl_job_failed id=%s error=%s", job_uuid, str(exc))
        with session_scope() as session:
            crawl_service.fail_crawl(session, job_uuid, str(exc))
        raise


def run_crawl_and_scrape_job(crawl_job_id: str, scrape_job_id: str) -> None:
    """Run crawl, then automatically enqueue scrape when crawl succeeds."""
    scrape_service = ScrapeService()
    scrape_uuid = uuid.UUID(scrape_job_id)

    try:
        run_crawl_job(crawl_job_id)
    except Exception as exc:
        logger.exception(
            "crawl_and_scrape_crawl_failed crawl_job_id=%s scrape_job_id=%s error=%s",
            crawl_job_id,
            scrape_job_id,
            str(exc),
        )
        with session_scope() as session:
            scrape_service.fail_scrape(session, scrape_uuid, f"Crawl phase failed: {exc}")
        raise

    enqueue_scrape(scrape_job_id)
    logger.info(
        "crawl_and_scrape_crawl_done crawl_job_id=%s scrape_job_id=%s scrape_enqueued=true",
        crawl_job_id,
        scrape_job_id,
    )


def run_scrape_job(job_id: str) -> None:
    """Orchestrator: enqueue one Redis/RQ task per crawl URL, then return."""
    scrape_service = ScrapeService()
    settings = get_settings()
    job_uuid = uuid.UUID(job_id)

    with session_scope() as session:
        job = scrape_service.get_job(session, job_uuid)
        if job is None:
            raise ValueError(f"Scrape job not found: {job_id}")
        if job.crawl_job.result is None:
            raise ValueError(f"Crawl result missing for scrape job: {job_id}")
        crawl_job_id = job.crawl_job_id
        embedding_source = job.embedding_source
        scrape_service.start_scrape(session, job_uuid)

    try:
        count = enqueue_scrape_pages(
            settings,
            scrape_job_id=job_uuid,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,  # type: ignore[arg-type]
        )
        logger.info(
            "scrape_job_orchestrated id=%s crawl_job_id=%s pages_enqueued=%d",
            job_uuid,
            crawl_job_id,
            count,
        )
        if count == 0:
            # No page tasks will run; finalize immediately so the job does not stay RUNNING.
            enqueue_scrape_finalize(job_id, str(crawl_job_id), embedding_source)
    except Exception as exc:
        logger.exception("scrape_job_orchestrate_failed id=%s error=%s", job_uuid, str(exc))
        with session_scope() as session:
            scrape_service.fail_scrape(session, job_uuid, str(exc))
        raise


def run_scrape_page(
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: str,
    url: str,
    index: int,
    depth: int,
    parent: str | None,
    stem: str,
    attempt: int = 0,
) -> None:
    """Worker task: scrape one URL, embed, store vector in Qdrant, cache result in Redis."""
    settings = get_settings()
    max_retries = settings.scrape_max_retries
    scrape_service = ScrapeService()

    with session_scope() as session:
        job = scrape_service.get_job(session, uuid.UUID(scrape_job_id))
        if job is None:
            raise ValueError(f"Scrape job not found: {scrape_job_id}")
        vector_config = ScrapeVectorConfig(
            qdrant_collection=job.qdrant_collection,
            embedding_model=job.embedding_model,
            sparse_embedding_model=job.sparse_embedding_model,
            pipeline_description=job.pipeline_description,
            use_sparse=job.use_sparse,
        )

    try:
        payload = asyncio.run(
            process_scrape_page(
                settings,
                scrape_job_id=scrape_job_id,
                crawl_job_id=crawl_job_id,
                embedding_source=embedding_source,  # type: ignore[arg-type]
                url=url,
                index=index,
                depth=depth,
                parent=parent,
                stem=stem,
                vector_config=vector_config,
            )
        )
        save_page_result(scrape_job_id, index=index, payload=payload)
    except Exception as exc:
        logger.exception(
            "scrape_page_task_failed scrape_job_id=%s index=%d url=%s attempt=%d error=%s",
            scrape_job_id,
            index,
            url,
            attempt,
            str(exc),
        )
        if attempt < max_retries:
            enqueue_scrape_page(
                scrape_job_id=scrape_job_id,
                crawl_job_id=crawl_job_id,
                embedding_source=embedding_source,
                url=url,
                index=index,
                depth=depth,
                parent=parent,
                stem=stem,
                attempt=attempt + 1,
            )
            logger.info(
                "scrape_page_requeued scrape_job_id=%s index=%d attempt=%d",
                scrape_job_id,
                index,
                attempt + 1,
            )
            return

        save_page_result(
            scrape_job_id,
            index=index,
            payload=failed_page_payload(
                index=index,
                url=url,
                depth=depth,
                parent=parent,
                stem=stem,
                error=str(exc),
            ),
        )

    if mark_page_finished(scrape_job_id) and try_schedule_finalize(scrape_job_id):
        enqueue_scrape_finalize(scrape_job_id, crawl_job_id, embedding_source)


def run_scrape_finalize(scrape_job_id: str, crawl_job_id: str, embedding_source: str) -> None:
    """After all page workers finish: write files to disk and complete scrape job in DB."""
    scrape_service = ScrapeService()
    settings = get_settings()
    job_uuid = uuid.UUID(scrape_job_id)

    try:
        output_dir, pages_scraped = finalize_scrape_job(
            settings,
            scrape_job_id=scrape_job_id,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,  # type: ignore[arg-type]
        )
        with session_scope() as session:
            scrape_service.complete_scrape(
                session,
                job_uuid,
                output_dir=str(output_dir.resolve()),
                pages_scraped=pages_scraped,
            )
            job = scrape_service.get_job(session, job_uuid)
            if job is not None and job.qdrant_collection is None:
                scrape_service.mark_crawl_indexing_complete(
                    session,
                    uuid.UUID(crawl_job_id),
                    embedding_source=embedding_source,  # type: ignore[arg-type]
                )
        logger.info(
            "scrape_job_completed id=%s pages_scraped=%d output_dir=%s",
            job_uuid,
            pages_scraped,
            str(output_dir),
        )
    except Exception as exc:
        logger.exception("scrape_finalize_failed id=%s error=%s", scrape_job_id, str(exc))
        with session_scope() as session:
            scrape_service.fail_scrape(session, job_uuid, str(exc))
        raise


def main() -> None:
    import sys

    from rq.cli import main as rq_main

    sys.argv = ["rq", "worker", "crawl", "scrape", "scrape-page"]
    rq_main()