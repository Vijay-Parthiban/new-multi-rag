"""Modality resolvers and the image chunk-index offset."""

from src.ingestion_service.core.page_yielder import FilePage
from src.ingestion_service.core.universal_fanout import (
    _assign_image_chunk_indexes,
    _chunk_pages,
    _resolve_image_embedding_model,
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


def test_resolve_text_embedding_model_prefers_the_profile() -> None:
    settings = get_settings()

    assert _resolve_text_embedding_model(KnowledgeProduct(name="t")) == settings.embedding_model

    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", text_embedding_model="Qwen-Embedding")
    assert _resolve_text_embedding_model(product) == "Qwen-Embedding"


def test_resolve_image_embedding_model_prefers_the_profile() -> None:
    settings = get_settings()

    assert (
        _resolve_image_embedding_model(KnowledgeProduct(name="t"))
        == settings.multimodal_embedding_model
    )

    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(
        name="p", image_embedding_model="Qwen-VL-Embedding"
    )
    assert _resolve_image_embedding_model(product) == "Qwen-VL-Embedding"


def test_assign_image_chunk_indexes_offsets_past_the_text_chunks() -> None:
    """Two records must never share a (page_index, chunk_index) pair.

    Both destinations key a record by that pair, so an image record beside the text
    chunks of its page has to start above them.
    """
    pages = [
        FilePage(page_index=0, text="a", chunk_index=0),
        FilePage(page_index=0, text="b", chunk_index=1),
        FilePage(page_index=0, text="page one", modality="image", image_ref={"page_index": 0}),
    ]

    out = _assign_image_chunk_indexes(pages)

    assert [p.chunk_index for p in out] == [0, 1, 2]
    assert out[2].modality == "image"
    assert out[2].image_ref == {"page_index": 0}
    # The text records are untouched.
    assert out[0].text == "a" and out[1].text == "b"


def test_chunking_keeps_the_image_modality_and_reference() -> None:
    """A long page-image record stays one image record per part.

    Its ``image_ref`` is what a reader downloads, so a split must not turn a part
    into an ordinary text chunk.
    """
    extracted = [
        FilePage(
            page_index=2,
            text=" ".join(["page"] * 80),
            modality="image",
            record_type="page",
            image_ref={"page_index": 2, "key": "_pages/f.pdf/page-00002.png"},
        )
    ]

    pages = _assign_image_chunk_indexes(_chunk_pages(extracted, 100, 10))

    assert len(pages) > 1
    assert all(p.modality == "image" for p in pages)
    assert all(p.image_ref == extracted[0].image_ref for p in pages)
    assert [p.chunk_index for p in pages] == list(range(len(pages)))
