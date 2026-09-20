import uuid

from src.ingestion_service.core.page_yielder import FilePage
from src.ingestion_service.core.universal_fanout import _build_fanout_payload
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE


def test_build_fanout_payload_matches_retrieval_contract() -> None:
    source_id = uuid.uuid4()
    product_id = uuid.uuid4()
    page = FilePage(page_index=2, text="Sample chunk text", chunk_index=2)

    payload = _build_fanout_payload(
        source_id=source_id,
        product_id=product_id,
        file_key="resumes/resume_alex.pdf",
        page=page,
    )

    assert payload["source_type"] == FILE_INGEST_SOURCE_TYPE
    assert payload["source_id"] == str(source_id)
    assert payload["source_locator"] == "resumes/resume_alex.pdf"
    assert payload["content"] == "Sample chunk text"
    assert payload["text"] == "Sample chunk text"
    assert payload["chunk_index"] == 2
    assert payload["file_name"] == "resume_alex.pdf"
    assert payload["knowledge_product_id"] == str(product_id)
    # The retrieval consumers read `type`, so a caption must stay text.
    assert payload["type"] == "text"
    assert payload["modality"] == "text"
    assert payload["image_ref"] is None


def test_build_fanout_payload_tags_a_captioned_figure() -> None:
    page = FilePage(
        page_index=1,
        text="A bar chart of quarterly capacity.",
        chunk_index=3,
        modality="image",
        image_ref={"page_index": 1, "image_index": 0},
    )

    payload = _build_fanout_payload(
        source_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        file_key="reports/q3.pdf",
        page=page,
    )

    assert payload["modality"] == "image"
    assert payload["image_ref"] == {"page_index": 1, "image_index": 0}
    assert payload["chunk_index"] == 3
    # A caption is text, so the retrieval contract is unchanged.
    assert payload["type"] == "text"
    assert payload["content"] == "A bar chart of quarterly capacity."
