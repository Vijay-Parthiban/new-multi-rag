"""PDF figure extraction: modality, filtering and the legacy render default."""

from pathlib import Path

from src.ingestion_service.core.page_yielder import iter_file_pages


def _fixture_pdf(tmp_path: Path, *, figure_px: int = 200) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Selectable body text.")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, figure_px, figure_px))
    pix.set_rect(pix.irect, (10, 120, 200))
    page.insert_image(fitz.Rect(72, 100, 272, 300), pixmap=pix)
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def test_embedded_figure_becomes_its_own_page(tmp_path: Path) -> None:
    path = _fixture_pdf(tmp_path)

    pages = list(
        iter_file_pages(path, None, "sample.pdf", render_pages=False, include_figures=True)
    )

    assert len(pages) == 2
    text_page, figure_page = pages
    assert text_page.modality == "text"
    assert text_page.text.strip() == "Selectable body text."
    assert text_page.image_png is None
    assert figure_page.modality == "image"
    assert figure_page.text == ""
    assert figure_page.image_ref == {"page_index": 0, "image_index": 0}
    # The figure is downscaled to JPEG, not kept as the original bytes.
    assert figure_page.image_png is not None
    assert figure_page.image_png.startswith(b"\xff\xd8")


def test_figures_are_off_by_default(tmp_path: Path) -> None:
    path = _fixture_pdf(tmp_path)

    pages = list(iter_file_pages(path, None, "sample.pdf", render_pages=False))

    assert len(pages) == 1
    assert pages[0].modality == "text"


def test_a_small_figure_is_filtered_out(tmp_path: Path) -> None:
    path = _fixture_pdf(tmp_path)

    pages = list(
        iter_file_pages(
            path,
            None,
            "sample.pdf",
            render_pages=False,
            include_figures=True,
            image_min_pixels=10_000_000,
        )
    )

    assert len(pages) == 1
    assert pages[0].modality == "text"


def test_render_pages_keeps_the_legacy_page_raster(tmp_path: Path) -> None:
    """The Pipeline path still gets a whole-page PNG on the text page."""
    path = _fixture_pdf(tmp_path)

    pages = list(iter_file_pages(path, None, "sample.pdf"))

    assert len(pages) == 1
    assert pages[0].modality == "text"
    assert pages[0].image_png is not None
    assert pages[0].image_png.startswith(b"\x89PNG")
