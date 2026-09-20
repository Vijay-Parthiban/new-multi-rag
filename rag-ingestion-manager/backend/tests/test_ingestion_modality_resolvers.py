"""Modality resolvers and the image chunk-index offset."""

from src.ingestion_service.core.page_yielder import FilePage
from src.ingestion_service.core.universal_fanout import (
    _assign_image_chunk_indexes,
    _chunk_pages,
    _resolve_caption_model,
    _resolve_image_min_pixels,
    _resolve_modality_mode,
    _resolve_text_embedding_model,
)
from src.shared.config.settings import get_settings
from src.shared.db.models import (
    DEFAULT_MODALITY_MODE,
    IngestionModality,
    IngestionProfile,
    KnowledgeProduct,
)


def test_resolve_modality_mode_defaults_to_text_without_a_profile() -> None:
    assert _resolve_modality_mode(KnowledgeProduct(name="t")) == DEFAULT_MODALITY_MODE
    assert DEFAULT_MODALITY_MODE == "text"


def test_resolve_modality_mode_reads_the_profile_enum() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(
        name="p", modality_mode=IngestionModality.TEXT_IMAGES
    )
    assert _resolve_modality_mode(product) == "text_images"


def test_resolve_caption_model_falls_back_to_settings() -> None:
    settings = get_settings()

    bare = KnowledgeProduct(name="t")
    assert _resolve_caption_model(bare) == settings.caption_model

    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", caption_model=None)
    assert _resolve_caption_model(product) == settings.caption_model

    product.ingestion_profile.caption_model = "nemotron-vision-NVIDIA"
    assert _resolve_caption_model(product) == "nemotron-vision-NVIDIA"


def test_resolve_text_embedding_model_prefers_the_profile() -> None:
    settings = get_settings()

    assert _resolve_text_embedding_model(KnowledgeProduct(name="t")) == settings.embedding_model

    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", text_embedding_model="Qwen-Embedding")
    assert _resolve_text_embedding_model(product) == "Qwen-Embedding"


def test_resolve_image_min_pixels_defaults_and_reads_the_profile() -> None:
    assert _resolve_image_min_pixels(KnowledgeProduct(name="t")) == 10000

    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", image_min_pixels=500)
    assert _resolve_image_min_pixels(product) == 500


def test_assign_image_chunk_indexes_offsets_past_the_text_chunks() -> None:
    pages = [
        FilePage(page_index=0, text="a", chunk_index=0),
        FilePage(page_index=0, text="b", chunk_index=1),
        FilePage(
            page_index=0,
            text="cap",
            modality="image",
            image_ref={"page_index": 0, "image_index": 0},
        ),
        FilePage(
            page_index=0,
            text="cap2",
            modality="image",
            image_ref={"page_index": 0, "image_index": 1},
        ),
    ]

    out = _assign_image_chunk_indexes(pages)

    assert [p.chunk_index for p in out] == [0, 1, 2, 3]
    assert out[2].modality == "image"
    assert out[2].image_ref == {"page_index": 0, "image_index": 0}
    # The text pages are untouched.
    assert out[0].text == "a" and out[1].text == "b"


def test_figures_on_a_text_free_page_start_at_zero_without_colliding() -> None:
    """A scanned page has no text chunks, so its figures own indexes from zero."""
    pages = [
        FilePage(
            page_index=0,
            text="cap one",
            modality="image",
            image_ref={"page_index": 0, "image_index": 0},
        ),
        FilePage(
            page_index=0,
            text="cap two",
            modality="image",
            image_ref={"page_index": 0, "image_index": 1},
        ),
    ]

    out = _assign_image_chunk_indexes(pages)

    assert [p.chunk_index for p in out] == [0, 1]


def test_figures_are_offset_per_page() -> None:
    """Two pages each with one figure keep separate (page, chunk) pairs."""
    pages = [
        FilePage(page_index=0, text="p0", chunk_index=0),
        FilePage(page_index=1, text="p1a", chunk_index=0),
        FilePage(page_index=1, text="p1b", chunk_index=1),
        FilePage(page_index=0, text="cap0", modality="image", image_ref={"page_index": 0, "image_index": 0}),
        FilePage(page_index=1, text="cap1", modality="image", image_ref={"page_index": 1, "image_index": 0}),
    ]

    out = _assign_image_chunk_indexes(pages)

    pairs = {(p.page_index, p.chunk_index) for p in out}
    assert len(pairs) == len(out), "two records share a (page_index, chunk_index) pair"
    image_pairs = {(p.page_index, p.chunk_index) for p in out if p.modality == "image"}
    assert image_pairs == {(0, 1), (1, 2)}


def test_chunking_keeps_the_figure_modality() -> None:
    """The real pipeline: extract, caption, chunk, then offset.

    A caption page must keep ``modality`` and ``image_ref`` through the split, or
    it becomes an ordinary text chunk that collides with the page's own first
    chunk.
    """
    extracted = [
        FilePage(page_index=0, text="Quarterly review.", chunk_index=0),
        FilePage(
            page_index=0,
            text="A blue rectangle with no labels.",
            modality="image",
            image_ref={"page_index": 0, "image_index": 0},
        ),
    ]

    pages = _assign_image_chunk_indexes(_chunk_pages(extracted, 1000, 100))

    image_pages = [p for p in pages if p.modality == "image"]
    assert len(image_pages) == 1
    assert image_pages[0].image_ref == {"page_index": 0, "image_index": 0}
    assert image_pages[0].chunk_index == 1
    pairs = {(p.page_index, p.chunk_index) for p in pages}
    assert len(pairs) == len(pages), "two records share a (page_index, chunk_index) pair"


def test_a_long_caption_splits_and_every_part_stays_an_image() -> None:
    extracted = [
        FilePage(
            page_index=2,
            text=" ".join(["caption"] * 80),
            modality="image",
            image_ref={"page_index": 2, "image_index": 1},
        )
    ]

    pages = _assign_image_chunk_indexes(_chunk_pages(extracted, 100, 10))

    assert len(pages) > 1
    assert all(p.modality == "image" for p in pages)
    assert all(p.image_ref == {"page_index": 2, "image_index": 1} for p in pages)
    assert [p.chunk_index for p in pages] == list(range(len(pages)))
