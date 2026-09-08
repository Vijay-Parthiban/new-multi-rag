import pytest
from rag_shared.types import RetrievedChunk

from eval_core.retrieval_metrics import compute_retrieval_metrics
from eval_core.source_match import is_relevant_chunk, normalize_source


def test_normalize_source_url():
    assert "arxiv.org" in normalize_source("https://www.arxiv.org/html/1706.03762v7")


def test_normalize_source_filename():
    assert normalize_source("/path/to/handbook.pdf") == "handbook.pdf"


def test_is_relevant_chunk_substring_match():
    chunk = RetrievedChunk(
        id="1",
        content="attention",
        source_type="web_scrape",
        source_id="job-1",
        source_locator="https://arxiv.org/html/1706.03762v7",
        chunk_index=0,
        chunk_type="text",
        retrieval_score=0.9,
    )
    assert is_relevant_chunk(chunk, {"1706.03762v7"})


def test_recall_at_k():
    chunks = [
        RetrievedChunk(
            id=str(i),
            content="x",
            source_type="web_scrape",
            source_id="j",
            source_locator=f"https://example.com/{i}",
            chunk_index=i,
            chunk_type="text",
            retrieval_score=1.0,
        )
        for i in range(3)
    ]
    chunks[2].source_locator = "https://arxiv.org/html/1706.03762v7"
    metrics = compute_retrieval_metrics(
        chunks,
        expected_sources=["1706.03762v7", "missing.pdf"],
        k_values=[3],
    )
    assert metrics["recall_at_3"] == 0.5
    assert metrics["hit_at_3"] == 1.0
