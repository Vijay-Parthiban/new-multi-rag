import csv
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FilePage:
    page_index: int
    text: str
    # A rendered PNG of the whole page: what the text_images modality embeds, and
    # what the legacy Pipeline path stores. None for every text format.
    image_png: bytes | None = None
    chunk_index: int = 0
    modality: str = "text"
    image_ref: dict[str, int] | None = None
    # "chunk" for a normal chunk, "parent" or "child" under the parent_child
    # chunk strategy. parent_ref names the parent record as
    # "<page_index>:<parent chunk_index>".
    record_type: str = "chunk"
    parent_ref: str | None = None

    def __post_init__(self) -> None:
        # A PDF can carry a NUL byte in its extracted text. PostgreSQL rejects a
        # string with 0x00, so psycopg2 fails the whole insert. Strip it here,
        # once, before any chunker or writer sees the text.
        if self.text and "\x00" in self.text:
            self.text = self.text.replace("\x00", "")


def iter_file_pages(
    path: Path,
    mime_type: str | None,
    original_name: str,
    *,
    render_pages: bool = True,
    render_dpi: int = 150,
    layout: bool = False,
) -> Iterator[FilePage]:
    """Yield one page at a time to limit RAM (PDF via PyMuPDF, structured formats via parsers).

    ``render_pages``, ``render_dpi`` and ``layout`` apply to PDFs only.
    ``render_pages`` is the Pipeline behaviour and stays the default, so the
    existing callers do not change. It renders one PNG of the whole page, which is
    what the ``text_images`` modality embeds; a caller that only needs text passes
    ``render_pages=False`` and reads rather less memory per page. It adds
    ``layout=True`` for the structure-aware chunk strategy, which needs the
    document's own block boundaries instead of its text stream.
    A DOCX already arrives as blank-line separated paragraphs, so that format and
    the plain-text formats need no flag.
    """
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()

    if suffix == ".pdf" or mime == "application/pdf":
        yield from _iter_pdf_pages(
            path,
            render_pages=render_pages,
            render_dpi=render_dpi,
            layout=layout,
        )
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


def _layout_text(page: Any) -> str:
    """Reading-order text blocks, one per layout block, blank-line separated.

    ``sort=True`` orders the blocks by position, so a two-column page comes out
    in reading order rather than in content-stream order. PyMuPDF groups a
    wrapped paragraph into one block and keeps a table region separate, so the
    blank line between blocks is the layout boundary the structure-aware chunk
    strategy splits on.
    """
    blocks: list[str] = []
    for block in page.get_text("blocks", sort=True) or []:
        # (x0, y0, x1, y1, text, block_no, block_type); block_type 0 is text.
        if len(block) < 7 or block[6] != 0:
            continue
        text = (block[4] or "").strip()
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


def _iter_pdf_pages(
    path: Path,
    *,
    render_pages: bool = True,
    render_dpi: int = 150,
    layout: bool = False,
) -> Iterator[FilePage]:
    import fitz

    doc = fitz.open(path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            text = _layout_text(page) if layout else (page.get_text("text") or "")
            if render_pages:
                pix = page.get_pixmap(dpi=render_dpi)
                png_bytes = pix.tobytes("png")
                yield FilePage(page_index=i, text=text, image_png=png_bytes)
                del pix
            else:
                yield FilePage(page_index=i, text=text)
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
