import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from crawler_db.base import Base
from crawler_db.enums import JobStatus
from crawler_db.services.crawl_service import CrawlService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_crawl_service_lifecycle(db_session):
    service = CrawlService()
    job = service.create_crawl_job(
        db_session,
        seed_url="https://example.com",
        max_depth=1,
        max_pages=5,
        crawl_mode="auto",
    )
    assert job.status == JobStatus.PENDING
    assert job.crawl_mode == "auto"

    service.start_crawl(db_session, job.id)
    db_session.refresh(job)
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None

    service.complete_crawl(
        db_session,
        job.id,
        links_file_path="/tmp/links.jsonl",
        total_links=3,
        pages_crawled=3,
        metadata={"duration_ms": 100},
    )
    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.result is not None
    assert job.result.links_file_path == "/tmp/links.jsonl"


def test_fail_crawl(db_session):
    service = CrawlService()
    job = service.create_crawl_job(
        db_session,
        seed_url="https://example.com",
        max_depth=0,
        max_pages=1,
    )
    service.start_crawl(db_session, job.id)
    service.fail_crawl(db_session, job.id, "network error")
    db_session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.error_message == "network error"


def test_crawl_service_rejects_invalid_mode(db_session):
    service = CrawlService()
    with pytest.raises(ValueError, match="crawl_mode must be one of: httpx, playwright, auto"):
        service.create_crawl_job(
            db_session,
            seed_url="https://example.com",
            max_depth=1,
            max_pages=5,
            crawl_mode="invalid",
        )
