import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("QDRANT_URL"),
    reason="QDRANT_URL not set; skipping integration test",
)


def test_retrieve_against_qdrant():
    from rag_shared.config import get_settings
    from retrieval_core import Retriever

    settings = get_settings()
    retriever = Retriever(settings)
    source_id = os.getenv("TEST_SOURCE_ID", "8b401860-3461-4ec7-88a5-3593e267b8aa")
    chunks = retriever.retrieve(
        "What is the attention mechanism?",
        source_type="web_scrape",
        source_id=source_id,
    )
    assert chunks
    assert any("arxiv" in c.source_locator.lower() for c in chunks)
