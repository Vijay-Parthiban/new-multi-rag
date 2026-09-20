from src.ingestion_service.core.page_yielder import FilePage
from src.ingestion_service.core.universal_fanout import _chunk_pages, _resolve_chunking
from src.shared.db.models import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    IngestionProfile,
    KnowledgeProduct,
)

_PARAGRAPH = "x" * 200


def _text(paragraphs: int) -> str:
    return "\n\n".join(_PARAGRAPH for _ in range(paragraphs))


def test_resolve_chunking_falls_back_without_a_profile() -> None:
    assert _resolve_chunking(KnowledgeProduct(name="t")) == (
        DEFAULT_CHUNK_SIZE,
        DEFAULT_CHUNK_OVERLAP,
    )


def test_resolve_chunking_reads_the_profile() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", chunk_size=200, chunk_overlap=20)

    assert _resolve_chunking(product) == (200, 20)


def test_resolve_chunking_clamps_an_overlap_at_the_size() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", chunk_size=200, chunk_overlap=500)

    assert _resolve_chunking(product) == (200, 199)


def test_chunk_pages_splits_a_page_and_numbers_the_chunks() -> None:
    pages = _chunk_pages([FilePage(page_index=3, text=_text(30))], 200, 20)

    assert len(pages) > 1
    assert all(page.page_index == 3 for page in pages)
    assert [page.chunk_index for page in pages] == list(range(len(pages)))


def test_chunk_pages_drops_a_blank_page() -> None:
    assert _chunk_pages([FilePage(page_index=0, text="")], 200, 20) == []


def test_chunk_pages_restarts_the_chunk_index_per_page() -> None:
    pages = _chunk_pages(
        [
            FilePage(page_index=0, text=_text(30)),
            FilePage(page_index=1, text=_text(30)),
            FilePage(page_index=2, text=_text(30)),
        ],
        200,
        20,
    )

    for page_index in (0, 1, 2):
        indexes = [p.chunk_index for p in pages if p.page_index == page_index]
        assert indexes == list(range(len(indexes)))


def test_chunk_pages_keeps_the_image_on_the_first_chunk_only() -> None:
    pages = _chunk_pages([FilePage(page_index=0, text=_text(30), image_png=b"png")], 200, 20)

    assert pages[0].image_png == b"png"
    assert all(page.image_png is None for page in pages[1:])
