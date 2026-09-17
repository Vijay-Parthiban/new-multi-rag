import csv
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FilePage:
    page_index: int
    text: str
    image_png: bytes | None = None


def iter_file_pages(path: Path, mime_type: str | None, original_name: str) -> Iterator[FilePage]:
    """Yield one page at a time to limit RAM (PDF via PyMuPDF, structured formats via parsers)."""
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()

    if suffix == ".pdf" or mime == "application/pdf":
        yield from _iter_pdf_pages(path)
        return

    if suffix == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        yield from _iter_docx_pages(path)
        return

    if suffix == ".csv" or mime in {"text/csv", "application/csv"}:
        yield from _iter_csv_pages(path)
        return

    if suffix == ".json" or mime == "application/json":
        yield from _iter_json_pages(path)
        return

    if suffix in {".md", ".markdown", ".txt", ".log"} or mime.startswith("text/"):
        text = path.read_text(encoding="utf-8", errors="replace")
        yield FilePage(page_index=0, text=text, image_png=None)
        return

    logger.warning(
        "page_yielder_fallback_utf8 path=%s suffix=%s mime=%s",
        original_name or path.name,
        suffix,
        mime or "unknown",
    )
    text = path.read_text(encoding="utf-8", errors="replace")
    yield FilePage(page_index=0, text=text, image_png=None)


def _iter_pdf_pages(path: Path) -> Iterator[FilePage]:
    import fitz

    doc = fitz.open(path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text") or ""
            pix = page.get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
            yield FilePage(page_index=i, text=text, image_png=png_bytes)
            del pix
    finally:
        doc.close()


def _iter_docx_pages(path: Path) -> Iterator[FilePage]:
    from docx import Document

    document = Document(path)
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)
    if not text.strip():
        yield FilePage(page_index=0, text="", image_png=None)
        return
    yield FilePage(page_index=0, text=text, image_png=None)


def _iter_csv_pages(path: Path) -> Iterator[FilePage]:
    lines: list[str] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            lines.append(", ".join(row))
    yield FilePage(page_index=0, text="\n".join(lines), image_png=None)


def _iter_json_pages(path: Path) -> Iterator[FilePage]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        yield FilePage(page_index=0, text=raw, image_png=None)
        return

    if isinstance(payload, list):
        chunks = [json.dumps(item, ensure_ascii=False) for item in payload]
        for index, chunk in enumerate(chunks):
            yield FilePage(page_index=index, text=chunk, image_png=None)
        return

    yield FilePage(page_index=0, text=json.dumps(payload, ensure_ascii=False, indent=2), image_png=None)
