import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from crawler_db.enums import JobStatus
from crawler_db.services.crawl_service import ScrapeService


def test_scrape_service_rejects_invalid_embedding_source() -> None:
    service = ScrapeService()
    session = MagicMock()
    crawl_id = uuid.uuid4()
    crawl_job = MagicMock()
    crawl_job.status = JobStatus.COMPLETED
    crawl_job.result = MagicMock()
    crawl_job.markdown_indexed_at = None
    crawl_job.image_indexed_at = None
    service._crawl_repo.get = MagicMock(return_value=crawl_job)

    with pytest.raises(ValueError, match="Invalid embedding_source"):
        service.create_scrape_job(session, crawl_job_id=crawl_id, embedding_source="video")


def test_scrape_service_rejects_duplicate_markdown_indexing() -> None:
    service = ScrapeService()
    session = MagicMock()
    crawl_id = uuid.uuid4()
    crawl_job = MagicMock()
    crawl_job.id = crawl_id
    crawl_job.status = JobStatus.COMPLETED
    crawl_job.result = MagicMock()
    crawl_job.markdown_indexed_at = datetime.now(UTC)
    crawl_job.image_indexed_at = None
    service._crawl_repo.get = MagicMock(return_value=crawl_job)

    with pytest.raises(ValueError, match="already has markdown vectors indexed"):
        service.create_scrape_job(session, crawl_job_id=crawl_id, embedding_source="markdown")
