import pytest
from reranker_core import NoopReranker
from rag_shared.types import RetrievedChunk


def test_noop_reranker_preserves_order():
    chunks = [
        RetrievedChunk(
            id=str(i),
            content=f"chunk {i}",
            source_type="web_scrape",
            source_id="j",
            source_locator="https://example.com",
            chunk_index=i,
            chunk_type="text",
            retrieval_score=float(3 - i),
        )
        for i in range(3)
    ]
    reranker = NoopReranker()
    result = reranker.rerank("query", chunks, top_k=2)
    assert len(result) == 2
    assert result[0].id == "0"
    assert result[0].rerank_score == 3.0
