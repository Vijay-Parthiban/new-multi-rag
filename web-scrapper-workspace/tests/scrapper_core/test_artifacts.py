import json
from pathlib import Path

from web_scrapper.storage.artifacts import (
    PAGES_MANIFEST_FILE,
    PageInMemory,
    build_page_record,
    persist_job_artifacts,
)


def test_build_record_and_background_persist(tmp_path: Path) -> None:
    job_root = tmp_path / "job-id"
    md_dir = job_root / "markdown"
    img_dir = job_root / "screenshots"

    page = PageInMemory(
        index=0,
        url="https://example.com",
        depth=0,
        parent=None,
        title="Example",
        markdown="# Example\n\nHi",
        screenshot_bytes=b"\x89PNG\r\n\x1a\n",
        markdown_path=md_dir / "00000-example-com.md",
        screenshot_path=img_dir / "00000-example-com.png",
        output_root=job_root,
    )

    record = build_page_record(page, include_image_base64=True)
    assert record.markdown_uri == "markdown/00000-example-com.md"
    assert record.image_base64 is not None

    persist_job_artifacts(
        output_root=job_root,
        manifest_path=job_root / PAGES_MANIFEST_FILE,
        scrape_job_id="job-id",
        crawl_job_id="crawl-id",
        embedding_source="markdown",
        pages=[page],
        records=[record],
        include_image_payload=True,
    )

    assert (md_dir / "00000-example-com.md").read_text(encoding="utf-8") == "# Example\n\nHi"
    manifest = json.loads((job_root / PAGES_MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["page_count"] == 1
