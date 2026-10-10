import json
from pathlib import Path

from src.ingestion_service.core.page_yielder import iter_file_pages


def _fixture_pdf(tmp_path: Path, *, pages: int = 2) -> Path:
    import fitz

    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Selectable body text {index}.")
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def test_iter_plain_text_file(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello ingestion", encoding="utf-8")

    pages = list(iter_file_pages(file_path, "text/plain", "notes.txt"))

    assert len(pages) == 1
    assert pages[0].page_index == 0
    assert pages[0].text == "hello ingestion"


def test_iter_json_file(tmp_path: Path) -> None:
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")

    pages = list(iter_file_pages(file_path, "application/json", "data.json"))

    assert len(pages) == 2
    assert '"id": 1' in pages[0].text
    assert '"id": 2' in pages[1].text


def test_iter_csv_file(tmp_path: Path) -> None:
    file_path = tmp_path / "rows.csv"
    file_path.write_text("name,role\nAlex,Engineer\n", encoding="utf-8")

    pages = list(iter_file_pages(file_path, "text/csv", "rows.csv"))

    assert len(pages) == 1
    assert "Alex, Engineer" in pages[0].text


def test_nul_byte_removed(tmp_path: Path) -> None:
    """PostgreSQL rejects a NUL byte, so no page text may carry one."""
    file_path = tmp_path / "notes.txt"
    file_path.write_bytes(b"before\x00after")

    pages = list(iter_file_pages(file_path, "text/plain", "notes.txt"))

    assert pages[0].text == "beforeafter"


def test_render_pages_yields_one_png_per_page(tmp_path: Path) -> None:
    """The text_images modality stores one page image per page, so each page must
    arrive with its own PNG."""
    path = _fixture_pdf(tmp_path, pages=3)

    pages = list(iter_file_pages(path, None, "sample.pdf"))

    assert [p.page_index for p in pages] == [0, 1, 2]
    assert all(p.image_png is not None for p in pages)
    assert all(p.image_png.startswith(b"\x89PNG") for p in pages)
    assert "Selectable body text 0." in pages[0].text


def test_render_pages_off_leaves_the_text_alone(tmp_path: Path) -> None:
    path = _fixture_pdf(tmp_path, pages=1)

    pages = list(iter_file_pages(path, None, "sample.pdf", render_pages=False))

    assert pages[0].image_png is None
    assert "Selectable body text 0." in pages[0].text


def test_render_dpi_decides_the_raster_size(tmp_path: Path) -> None:
    path = _fixture_pdf(tmp_path, pages=1)

    low = list(iter_file_pages(path, None, "sample.pdf", render_dpi=72))[0].image_png
    high = list(iter_file_pages(path, None, "sample.pdf", render_dpi=150))[0].image_png

    assert low is not None and high is not None
    assert len(high) > len(low)
