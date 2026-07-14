import base64
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PAGES_MANIFEST_FILE = "pages_manifest.json"
IMAGE_EMBEDDINGS_FILE = "embeddings_payload.json"


@dataclass
class PageInMemory:
    """Scraped page kept in memory until embeddings and DB work finish."""

    index: int
    url: str
    depth: int
    parent: str | None
    title: str | None
    markdown: str
    screenshot_bytes: bytes
    markdown_path: Path
    screenshot_path: Path
    output_root: Path


@dataclass
class PageArtifactRecord:
    """Metadata for one scraped page (paths relative to scrape job output root)."""

    index: int
    url: str
    depth: int
    parent: str | None
    title: str | None
    markdown_uri: str
    screenshot_uri: str
    screenshot_file_uri: str
    image_base64: str | None = None


def build_page_record(
    page: PageInMemory,
    *,
    include_image_base64: bool,
) -> PageArtifactRecord:
    """Build manifest metadata from in-memory content (no disk I/O)."""
    rel_md = page.markdown_path.relative_to(page.output_root).as_posix()
    rel_png = page.screenshot_path.relative_to(page.output_root).as_posix()
    image_b64: str | None = None
    if include_image_base64:
        image_b64 = base64.b64encode(page.screenshot_bytes).decode("ascii")

    return PageArtifactRecord(
        index=page.index,
        url=page.url,
        depth=page.depth,
        parent=page.parent,
        title=page.title,
        markdown_uri=rel_md,
        screenshot_uri=rel_png,
        screenshot_file_uri=page.screenshot_path.resolve().as_uri(),
        image_base64=image_b64,
    )


def persist_page_files(page: PageInMemory) -> None:
    """Write markdown and screenshot for one page (background thread)."""
    page.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    page.markdown_path.write_text(page.markdown, encoding="utf-8")
    page.screenshot_path.write_bytes(page.screenshot_bytes)
    logger.debug(
        "page_files_persisted url=%s markdown=%s screenshot=%s",
        page.url,
        page.markdown_path.name,
        page.screenshot_path.name,
    )


def persist_job_artifacts(
    *,
    output_root: Path,
    manifest_path: Path,
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: str,
    pages: list[PageInMemory],
    records: list[PageArtifactRecord],
    include_image_payload: bool,
) -> None:
    """Persist all page files and JSON indexes (runs after embeddings)."""
    for page in pages:
        persist_page_files(page)

    payload = {
        "scrape_job_id": scrape_job_id,
        "crawl_job_id": crawl_job_id,
        "embedding_source": embedding_source,
        "page_count": len(records),
        "pages": [asdict(record) for record in records],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("pages_manifest_written path=%s pages=%d", str(manifest_path), len(records))

    if include_image_payload and records:
        image_pages = [
            {
                "url": record.url,
                "depth": record.depth,
                "parent": record.parent,
                "screenshot_uri": record.screenshot_uri,
                "screenshot_file_uri": record.screenshot_file_uri,
                "image_base64": record.image_base64,
                "mime_type": "image/png",
            }
            for record in records
            if record.image_base64 is not None
        ]
        image_path = output_root / "screenshots" / IMAGE_EMBEDDINGS_FILE
        image_path.write_text(json.dumps(image_pages, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("image_embeddings_payload_written path=%s records=%d", str(image_path), len(image_pages))
