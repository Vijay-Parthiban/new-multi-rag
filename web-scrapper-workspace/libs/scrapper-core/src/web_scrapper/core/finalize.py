import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from crawler_shared.config import Settings
from crawler_shared.redis.scrape_coordinator import cleanup_scrape_job, load_page_results
from crawler_shared.storage.background_io import flush_background_writes
from crawler_shared.types import EmbeddingSource

from web_scrapper.storage.artifacts import (
    PAGES_MANIFEST_FILE,
    PageArtifactRecord,
    PageInMemory,
    persist_job_artifacts,
)

logger = logging.getLogger(__name__)


def finalize_scrape_job(
    settings: Settings,
    *,
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: EmbeddingSource,
) -> tuple[Path, int]:
    """Load page results from Redis, write all files to disk, return output path and success count."""
    output_root = settings.scrape_data_dir / scrape_job_id
    raw_pages = load_page_results(scrape_job_id)

    in_memory_pages: list[PageInMemory] = []
    records: list[PageArtifactRecord] = []

    for item in raw_pages:
        if not item.get("success", False):
            continue
        stem = str(item["stem"])
        page = PageInMemory(
            index=int(item["index"]),
            url=str(item["url"]),
            depth=int(item["depth"]),
            parent=item.get("parent"),
            title=item.get("title"),
            markdown=str(item["markdown"]),
            screenshot_bytes=base64.b64decode(str(item["screenshot_b64"])),
            markdown_path=output_root / "markdown" / f"{stem}.md",
            screenshot_path=output_root / "screenshots" / f"{stem}.png",
            output_root=output_root,
        )
        in_memory_pages.append(page)
        records.append(
            PageArtifactRecord(
                index=page.index,
                url=page.url,
                depth=page.depth,
                parent=page.parent,
                title=page.title,
                markdown_uri=str(item["markdown_uri"]),
                screenshot_uri=str(item["screenshot_uri"]),
                screenshot_file_uri=str(item.get("screenshot_file_uri") or ""),
                image_base64=item.get("image_base64"),
            )
        )

    pages_scraped = len(in_memory_pages)
    if pages_scraped == 0:
        cleanup_scrape_job(scrape_job_id)
        return output_root, 0

    manifest_path = output_root / PAGES_MANIFEST_FILE
    io_workers = max(1, settings.scrape_io_workers)
    include_image_payload = embedding_source == "image"

    with ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="scrape-io") as io_pool:
        flush_background_writes(
            io_pool,
            [
                partial(
                    persist_job_artifacts,
                    output_root=output_root,
                    manifest_path=manifest_path,
                    scrape_job_id=scrape_job_id,
                    crawl_job_id=crawl_job_id,
                    embedding_source=embedding_source,
                    pages=in_memory_pages,
                    records=records,
                    include_image_payload=include_image_payload,
                )
            ],
            label="scrape_persist",
        )

    cleanup_scrape_job(scrape_job_id)
    logger.info(
        "scrape_finalize_done scrape_job_id=%s pages_scraped=%d output=%s",
        scrape_job_id,
        pages_scraped,
        str(output_root),
    )
    return output_root, pages_scraped
