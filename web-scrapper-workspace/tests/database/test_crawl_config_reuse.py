import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from crawler_db.enums import JobStatus
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.scrape_job import ScrapeJob
from crawler_db.services.crawl_service import CrawlService, ScrapeService


def test_find_completed_crawl_by_config_delegates_to_repo() -> None:
    service = CrawlService()
    session = MagicMock()
    expected = CrawlJob(
        id=uuid.uuid4(),
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="playwright",
        status=JobStatus.COMPLETED,
    )
    service._repo.find_completed_by_config = MagicMock(return_value=expected)

    result = service.find_completed_crawl_by_config(
        session,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="playwright",
    )

    assert result is expected
    service._repo.find_completed_by_config.assert_called_once()


def test_is_embedding_source_indexed_uses_crawl_job_flags() -> None:
    service = ScrapeService()
    crawl_job = CrawlJob(
        id=uuid.uuid4(),
        seed_url="https://example.com",
        max_depth=1,
        max_pages=5,
        crawl_mode="httpx",
        status=JobStatus.COMPLETED,
        markdown_indexed_at=datetime.now(UTC),
        image_indexed_at=None,
    )

    assert service.is_embedding_source_indexed(crawl_job, "markdown") is True
    assert service.is_embedding_source_indexed(crawl_job, "image") is False


def test_find_completed_scrape_for_crawl_delegates_to_repo() -> None:
    service = ScrapeService()
    session = MagicMock()
    crawl_id = uuid.uuid4()
    expected = ScrapeJob(
        id=uuid.uuid4(),
        crawl_job_id=crawl_id,
        status=JobStatus.COMPLETED,
        embedding_source="markdown",
        pages_scraped=3,
    )
    service._scrape_repo.find_completed_for_crawl = MagicMock(return_value=expected)

    result = service.find_completed_scrape_for_crawl(
        session,
        crawl_job_id=crawl_id,
        embedding_source="markdown",
    )

    assert result is expected
