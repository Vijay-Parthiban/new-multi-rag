import csv
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.shared.db.models import DEFAULT_IMAGE_MIN_PIXELS

logger = logging.getLogger(__name__)


@dataclass
class FilePage:
    page_index: int
    text: str
    # A rendered page PNG on the legacy Pipeline path, or a downscaled JPEG of one
    # embedded figure when the fanout asks for figures.
    image_png: bytes | None = None
    chunk_index: int = 0
    modality: str = "text"
    image_ref: dict[str, int] | None = None
    # "chunk" for a normal chunk, "parent" or "child" under the parent_child
    # chunk strategy. parent_ref names the parent record as
    # "<page_index>:<parent chunk_index>".
    record_type: str = "chunk"
    parent_ref: str | None = None


def iter_file_pages(
    path: Path,
    mime_type: str | None,
    original_name: str,
    *,
    render_pages: bool = True,
    include_figures: bool = False,
    layout: bool = False,
    image_min_pixels: int = DEFAULT_IMAGE_MIN_PIXELS,
) -> Iterator[FilePage]:
    """Yield one page at a time to limit RAM (PDF via PyMuPDF, structured formats via parsers).

    ``render_pages``, ``include_figures`` and ``layout`` apply to PDFs only.
    ``render_pages`` is the Pipeline behaviour and stays the default, so the
    existing callers do not change. The fanout passes ``render_pages=False,
    include_figures=True``: it captions embedded figures and never needs a
    whole-page raster. It adds ``layout=True`` for the ``layout`` chunk strategy,
    which needs the document's own block boundaries instead of its text stream.
    A DOCX already arrives as blank-line separated paragraphs, so that format and
    the plain-text formats need no flag.
    """
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()

    if suffix == ".pdf" or mime == "application/pdf":
        yield from _iter_pdf_pages(
            path,
            render_pages=render_pages,
            include_figures=include_figures,
            layout=layout,
            image_min_pixels=image_min_pixels,
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


def _figure_jpeg(doc: Any, xref: int, image_min_pixels: int) -> bytes | None:
    """Downscaled JPEG for one embedded image, or None when it is too small.

    Halves the dimensions while they exceed 1024 px, because vision-model cost
    scales with image resolution.
    """
    import fitz

    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.width * pix.height < image_min_pixels:
            return None
        while max(pix.width, pix.height) > 1024:
            pix.shrink(1)
        return pix.tobytes("jpeg")
    except Exception as exc:
        logger.warning("pdf_figure_skipped xref=%s error=%s", xref, exc)
        return None


def _layout_text(page: Any) -> str:
    """Reading-order text blocks, one per layout block, blank-line separated.

    ``sort=True`` orders the blocks by position, so a two-column page comes out
    in reading order rather than in content-stream order. PyMuPDF groups a
    wrapped paragraph into one block and keeps a table region separate, so the
    blank line between blocks is the layout boundary the ``layout`` chunk
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
    include_figures: bool = False,
    layout: bool = False,
    image_min_pixels: int = DEFAULT_IMAGE_MIN_PIXELS,
) -> Iterator[FilePage]:
    import fitz

    doc = fitz.open(path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            text = _layout_text(page) if layout else (page.get_text("text") or "")
            if render_pages:
                pix = page.get_pixmap(dpi=150)
                png_bytes = pix.tobytes("png")
                yield FilePage(page_index=i, text=text, image_png=png_bytes)
                del pix
            else:
                yield FilePage(page_index=i, text=text)

            if not include_figures:
                continue
            for n, info in enumerate(page.get_images(full=True)):
                image = _figure_jpeg(doc, info[0], image_min_pixels)
                if image is None:
                    continue
                yield FilePage(
                    page_index=i,
                    text="",
                    image_png=image,
                    modality="image",
                    image_ref={"page_index": i, "image_index": n},
                )
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
