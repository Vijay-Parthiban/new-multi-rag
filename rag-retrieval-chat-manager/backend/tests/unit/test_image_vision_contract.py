"""The contract between an ingestion page-image record and this reader.

A text-with-images product writes one record per page: ``type`` "image", the page
text in ``content``, and the rendered page in ``image_base64``. This side must
recognise it as an image, rebuild the bytes for the model call, and still show the
page text wherever a reader has no vision model.
"""

from rag_core.assistant import (
    StrategyUnavailable,
    resolve_strategy,
    stores_for_product,
    strategies_for_product,
)
from rag_shared.chunk_utils import (
    image_data_uri,
    is_image_chunk,
    passage_text_for_chunk,
    split_chunks,
)
from rag_shared.types import KpStores
from retrieval_core.hit_mapper import chunk_from_search_hit

PAGE_TEXT = "Quarterly capacity rose by 12 percent."
PAGE_BASE64 = "aGVsbG8="


def _hit(**overrides: object) -> dict:
    """One record as the fanout writes it, after the shared hit mapper."""
    return {
        "id": "point-1",
        "score": 0.81,
        "type": "image",
        "content": PAGE_TEXT,
        "text": PAGE_TEXT,
        "source_type": "file_ingest",
        "source_id": "src-1",
        "source_locator": "reports/q3.pdf",
        "chunk_index": 0,
        "title": "q3.pdf",
        "source_url": "reports/q3.pdf",
        "scrape_job_id": "src-1",
        "image_base64": PAGE_BASE64,
        "mime_type": "image/png",
        "file_name": "q3.pdf",
        "page_index": 1,
        "file_key": "reports/q3.pdf",
        **overrides,
    }


def test_a_page_image_record_reads_as_an_image_with_a_text_caption() -> None:
    chunk = chunk_from_search_hit(_hit())

    assert is_image_chunk(chunk)
    assert image_data_uri(chunk) == f"data:image/png;base64,{PAGE_BASE64}"
    text_chunks, image_chunks = split_chunks([chunk])
    assert text_chunks == []
    assert image_chunks == [chunk]
    # The sources panel and the answer judge read words, not bytes.
    assert passage_text_for_chunk(chunk) == PAGE_TEXT


def test_a_text_record_is_unchanged() -> None:
    chunk = chunk_from_search_hit(
        _hit(type="text", image_base64=None, mime_type=None)
    )

    assert not is_image_chunk(chunk)
    assert image_data_uri(chunk) is None
    assert passage_text_for_chunk(chunk) == chunk.content


def test_a_text_images_product_serves_only_the_page_image_strategy() -> None:
    destinations = [
        {
            "destination_type": "vector_qdrant",
            "enabled": True,
            "config": {"collection_name": "kp_x"},
        },
        {
            "destination_type": "lexical_opensearch",
            "enabled": True,
            "config": {"index_name": "kp:x"},
        },
    ]

    assert strategies_for_product(destinations, "text_images") == ["image_vision"]
    # The same product without the page-image modality keeps its text modes.
    assert strategies_for_product(destinations) == [
        "vector",
        "lexical",
        "hybrid",
        "self_rag",
        "corrective",
    ]


def test_the_page_image_strategy_needs_the_vector_store() -> None:
    try:
        resolve_strategy("image_vision", KpStores())
    except StrategyUnavailable as exc:
        assert "vector_qdrant" in exc.missing
    else:
        raise AssertionError("image_vision must need the vector store")

    resolve_strategy(
        "image_vision",
        stores_for_product(
            [
                {
                    "destination_type": "vector_qdrant",
                    "enabled": True,
                    "config": {"collection_name": "kp_x"},
                }
            ]
        ),
    )
