import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app, get_db
from crawler_db.enums import JobStatus
from crawler_db.models.scrape_job import ScrapeJob
from web_scrapper.storage.artifacts import PAGES_MANIFEST_FILE


def _write_job_dir(root: Path, *, escaping: bool = False) -> Path:
    """Create a fake scrape job output dir: two pages, one of them escaping the root."""
    markdown_dir = root / "markdown"
    screenshot_dir = root / "screenshots"
    markdown_dir.mkdir(parents=True)
    screenshot_dir.mkdir(parents=True)
    (markdown_dir / "00000-example-com.md").write_text(
        "# Example Domain\n\nHello.", encoding="utf-8", newline="\n"
    )
    (screenshot_dir / "00000-example-com.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    pages = [
        {
            "index": 0,
            "url": "https://example.com",
            "depth": 0,
            "parent": None,
            "title": "Example Domain",
            "markdown_uri": "markdown/00000-example-com.md",
            "screenshot_uri": "screenshots/00000-example-com.png",
            "screenshot_file_uri": (screenshot_dir / "00000-example-com.png").resolve().as_uri(),
            "image_base64": None,
        },
        {
            "index": 1,
            "url": "https://example.com/escape",
            "depth": 1,
            "parent": "https://example.com",
            "title": "Escape" if escaping else None,
            "markdown_uri": "../../outside.md" if escaping else "markdown/00001-escape.md",
            "screenshot_uri": "screenshots/00001-escape.png",
            "screenshot_file_uri": "",
            "image_base64": None,
        },
    ]
    if not escaping:
        (markdown_dir / "00001-escape.md").write_text("# Escape", encoding="utf-8")
        (screenshot_dir / "00001-escape.png").write_bytes(b"\x89PNG\r\n\x1a\nfake2")

    (root / PAGES_MANIFEST_FILE).write_text(
        json.dumps(
            {
                "scrape_job_id": str(uuid4()),
                "crawl_job_id": str(uuid4()),
                "embedding_source": "none",
                "page_count": len(pages),
                "pages": pages,
            }
        ),
        encoding="utf-8",
    )
    return root


def _client_for(job: ScrapeJob) -> tuple[TestClient, MagicMock]:
    mock_db = MagicMock()
    mock_scrape_service = MagicMock()
    mock_scrape_service.get_job.return_value = job
    service_patch = patch("api.main.scrape_service", mock_scrape_service)

    def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), service_patch


def _run(tmp_path: Path, job: ScrapeJob, request):
    client, service_patch = _client_for(job)
    with service_patch:
        try:
            return request(client)
        finally:
            app.dependency_overrides.clear()


def test_pages_route_lists_manifest_records(tmp_path):
    root = _write_job_dir(tmp_path / "job")
    job = ScrapeJob(
        id=uuid4(),
        crawl_job_id=uuid4(),
        status=JobStatus.COMPLETED,
        embedding_source="none",
        pages_scraped=2,
        output_dir=str(root),
    )

    response = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["page_count"] == 2
    assert body["pages"][0]["markdown_uri"] == "markdown/00000-example-com.md"
    assert body["pages"][0]["url"] == "https://example.com"


def test_markdown_and_screenshot_routes_serve_page_files(tmp_path):
    root = _write_job_dir(tmp_path / "job")
    job = ScrapeJob(
        id=uuid4(),
        crawl_job_id=uuid4(),
        status=JobStatus.COMPLETED,
        embedding_source="none",
        pages_scraped=2,
        output_dir=str(root),
    )

    markdown = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages/0/markdown"))
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text == "# Example Domain\n\nHello."

    screenshot = _run(
        tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages/0/screenshot")
    )
    assert screenshot.status_code == 200
    assert screenshot.headers["content-type"] == "image/png"
    assert screenshot.content == b"\x89PNG\r\n\x1a\nfake"


def test_unknown_page_index_is_404(tmp_path):
    root = _write_job_dir(tmp_path / "job")
    job = ScrapeJob(
        id=uuid4(),
        crawl_job_id=uuid4(),
        status=JobStatus.COMPLETED,
        embedding_source="none",
        pages_scraped=2,
        output_dir=str(root),
    )

    response = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages/9/markdown"))

    assert response.status_code == 404
    assert response.json()["detail"] == "Page index not found"


def test_manifest_path_outside_output_dir_is_rejected(tmp_path):
    root = _write_job_dir(tmp_path / "job", escaping=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    job = ScrapeJob(
        id=uuid4(),
        crawl_job_id=uuid4(),
        status=JobStatus.COMPLETED,
        embedding_source="none",
        pages_scraped=2,
        output_dir=str(root),
    )

    response = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages/1/markdown"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid artifact path"


def test_missing_output_dir_and_manifest_are_404(tmp_path):
    job = ScrapeJob(
        id=uuid4(),
        crawl_job_id=uuid4(),
        status=JobStatus.COMPLETED,
        embedding_source="none",
        pages_scraped=0,
        output_dir=None,
    )
    response = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Scrape job has no artifacts"

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    job.output_dir = str(empty_root)
    response = _run(tmp_path, job, lambda client: client.get(f"/scrapes/{job.id}/pages"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Pages manifest not found"
