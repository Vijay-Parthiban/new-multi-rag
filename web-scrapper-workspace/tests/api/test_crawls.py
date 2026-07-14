from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.enums import JobStatus


def test_create_crawl_returns_job_id():
    job_id = uuid4()
    mock_job = CrawlJob(
        id=job_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="auto",
        status=JobStatus.PENDING,
    )

    with patch("api.main.crawl_service") as mock_service, patch("api.main.enqueue_crawl") as mock_enqueue:
        mock_service.create_crawl_job.return_value = mock_job
        mock_service.get_job.return_value = mock_job

        mock_db = MagicMock()
        app.dependency_overrides.clear()

        from api.main import get_db

        def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)
        response = client.post(
            "/crawls",
            json={"seed_url": "https://example.com", "max_depth": 2, "max_pages": 10, "mode": "auto"},
        )
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["id"] == str(job_id)
    assert response.json()["mode"] == "auto"
    mock_enqueue.assert_called_once_with(job_id)


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_links_returns_json_records(tmp_path):
    # Create a tiny jsonl links file on disk
    links_path = tmp_path / "links.jsonl"
    links_path.write_text(
        '{"url":"https://example.com/file.pdf","depth":1,"parent":"https://example.com","status_code":null}\n',
        encoding="utf-8",
    )

    job_id = uuid4()
    mock_job = CrawlJob(
        id=job_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="httpx",
        status=JobStatus.COMPLETED,
    )
    mock_job.result = MagicMock(links_file_path=str(links_path))

    with patch("api.main.crawl_service") as mock_service:
        mock_service.get_job.return_value = mock_job
        client = TestClient(app)
        response = client.get(f"/crawls/{job_id}/links?limit=10&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["url"] == "https://example.com/file.pdf"


def test_get_links_download_returns_file(tmp_path):
    links_path = tmp_path / "links.jsonl"
    links_path.write_text('{"url":"https://example.com/file.pdf","depth":1}\n', encoding="utf-8")

    job_id = uuid4()
    mock_job = CrawlJob(
        id=job_id,
        seed_url="https://example.com",
        max_depth=2,
        max_pages=10,
        crawl_mode="httpx",
        status=JobStatus.COMPLETED,
    )
    mock_job.result = MagicMock(links_file_path=str(links_path))

    with patch("api.main.crawl_service") as mock_service:
        mock_service.get_job.return_value = mock_job
        client = TestClient(app)
        response = client.get(f"/crawls/{job_id}/links?download=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert b"file.pdf" in response.content
