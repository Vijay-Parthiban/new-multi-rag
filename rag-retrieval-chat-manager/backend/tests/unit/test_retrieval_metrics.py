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


def _chunk(index: int, locator: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=str(index),
        content="x",
        source_type="web_scrape",
        source_id="j",
        source_locator=locator,
        chunk_index=index,
        chunk_type="text",
        retrieval_score=1.0,
    )


def test_map_rewards_higher_rank():
    relevant = "https://arxiv.org/html/1706.03762v7"
    at_rank_1 = [
        _chunk(0, relevant),
        _chunk(1, "https://example.com/a"),
        _chunk(2, "https://example.com/b"),
    ]
    at_rank_3 = [
        _chunk(0, "https://example.com/a"),
        _chunk(1, "https://example.com/b"),
        _chunk(2, relevant),
    ]

    assert compute_retrieval_metrics(at_rank_1, [relevant])["map"] == 1.0
    assert compute_retrieval_metrics(at_rank_3, [relevant])["map"] == pytest.approx(1 / 3)


def test_k_values_emit_at_k_keys():
    metrics = compute_retrieval_metrics(
        [_chunk(0, "https://example.com/a")], ["a.pdf"], k_values=[1, 3, 5, 10]
    )

    assert "precision_at_1" in metrics
    assert "recall_at_3" in metrics
    assert "hit_at_5" in metrics
    assert "ndcg_at_10" in metrics
    assert "map" in metrics
    assert "mrr" in metrics
    assert "precision" not in metrics


def test_no_expected_sources_returns_an_empty_block():
    # A row without a source cannot be scored, and a zero would read as a failure.
    assert compute_retrieval_metrics([_chunk(0, "https://example.com/a")], []) == {}
