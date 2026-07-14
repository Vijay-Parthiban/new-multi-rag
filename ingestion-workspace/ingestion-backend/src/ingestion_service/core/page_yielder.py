from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path


@dataclass
class FilePage:
    page_index: int
    text: str
    image_png: bytes | None = None


def iter_file_pages(path: Path, mime_type: str | None, original_name: str) -> Iterator[FilePage]:
    """Yield one page at a time to limit RAM (PDF via PyMuPDF, plain text as single page)."""
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()

    if suffix == ".pdf" or mime == "application/pdf":
        yield from _iter_pdf_pages(path)
        return

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
