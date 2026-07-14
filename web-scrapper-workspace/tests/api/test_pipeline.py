from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app
from crawler_db.enums import JobStatus
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.scrape_job import ScrapeJob


def _post_pipeline(client: TestClient) -> dict:
    response = client.post(
        "/pipelines/crawl-scrape",
        json={
            "seed_url": "https://example.com",
            "max_depth": 2,
            "max_pages": 10,
            "mode": "playwright",
            "embedding_source": "markdown",
        },
    )
    return response


def test_create_crawl_scrape_pipeline_returns_both_jobs():
    crawl_id = uuid4()
    scrape_id = uuid4()
    mock_crawl = CrawlJob(
        id=crawl_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="playwright",
        status=JobStatus.PENDING,
    )
    mock_scrape = ScrapeJob(
        id=scrape_id,
        crawl_job_id=crawl_id,
        status=JobStatus.PENDING,
        embedding_source="markdown",
        pages_scraped=0,
    )

    with (
        patch("api.main.crawl_service") as mock_crawl_service,
        patch("api.main.scrape_service") as mock_scrape_service,
        patch("api.main.enqueue_crawl_and_scrape") as mock_enqueue,
    ):
        mock_crawl_service.find_completed_crawl_by_config.return_value = None
        mock_crawl_service.create_crawl_job.return_value = mock_crawl
        mock_crawl_service.get_job.return_value = mock_crawl
        mock_scrape_service.create_pending_scrape_job.return_value = mock_scrape
        mock_scrape_service.get_job.return_value = mock_scrape

        mock_db = MagicMock()
        from api.main import get_db

        def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = _post_pipeline(client)
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["skipped"] is False
    assert body["crawl_job"]["id"] == str(crawl_id)
    assert body["scrape_job"]["id"] == str(scrape_id)
    mock_enqueue.assert_called_once_with(crawl_id, scrape_id)


def test_create_crawl_scrape_pipeline_skips_when_already_ingested():
    crawl_id = uuid4()
    scrape_id = uuid4()
    mock_crawl = CrawlJob(
        id=crawl_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="playwright",
        status=JobStatus.COMPLETED,
    )
    mock_scrape = ScrapeJob(
        id=scrape_id,
        crawl_job_id=crawl_id,
        status=JobStatus.COMPLETED,
        embedding_source="markdown",
        pages_scraped=5,
    )

    with (
        patch("api.main.crawl_service") as mock_crawl_service,
        patch("api.main.scrape_service") as mock_scrape_service,
        patch("api.main.enqueue_crawl_and_scrape") as mock_enqueue,
        patch("api.main.enqueue_scrape") as mock_enqueue_scrape,
    ):
        mock_crawl_service.find_completed_crawl_by_config.return_value = mock_crawl
        mock_scrape_service.is_embedding_source_indexed.return_value = True
        mock_scrape_service.find_completed_scrape_for_crawl.return_value = mock_scrape

        mock_db = MagicMock()
        from api.main import get_db

        def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = _post_pipeline(client)
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["skipped"] is True
    assert body["skip_reason"] is not None
    mock_enqueue.assert_not_called()
    mock_enqueue_scrape.assert_not_called()


def test_create_crawl_scrape_pipeline_reuses_completed_crawl():
    crawl_id = uuid4()
    scrape_id = uuid4()
    mock_crawl = CrawlJob(
        id=crawl_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="playwright",
        status=JobStatus.COMPLETED,
    )
    mock_scrape = ScrapeJob(
        id=scrape_id,
        crawl_job_id=crawl_id,
        status=JobStatus.PENDING,
        embedding_source="image",
        pages_scraped=0,
    )

    with (
        patch("api.main.crawl_service") as mock_crawl_service,
        patch("api.main.scrape_service") as mock_scrape_service,
        patch("api.main.enqueue_crawl_and_scrape") as mock_enqueue,
        patch("api.main.enqueue_scrape") as mock_enqueue_scrape,
    ):
        mock_crawl_service.find_completed_crawl_by_config.return_value = mock_crawl
        mock_scrape_service.is_embedding_source_indexed.return_value = False
        mock_scrape_service.create_pending_scrape_job.return_value = mock_scrape
        mock_crawl_service.get_job.return_value = mock_crawl
        mock_scrape_service.get_job.return_value = mock_scrape

        mock_db = MagicMock()
        from api.main import get_db

        def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.post(
            "/pipelines/crawl-scrape",
            json={
                "seed_url": "https://example.com",
                "max_depth": 2,
                "max_pages": 10,
                "mode": "playwright",
                "embedding_source": "image",
            },
        )
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["skipped"] is False
    mock_crawl_service.create_crawl_job.assert_not_called()
    mock_enqueue.assert_not_called()
    mock_enqueue_scrape.assert_called_once_with(scrape_id)
