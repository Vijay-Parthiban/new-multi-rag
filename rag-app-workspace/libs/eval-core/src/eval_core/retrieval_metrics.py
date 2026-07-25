from __future__ import annotations

from typing import Any

from rag_shared.types import RetrievedChunk

from eval_core.source_match import ExpectedSource, is_relevant_chunk, parse_expected_sources


ExpectedSources = list[str] | list[ExpectedSource] | list[Any]


def hit_at_k(chunks: list[RetrievedChunk], expected: ExpectedSources, k: int) -> float:
    sources = parse_expected_sources(expected)
    top = chunks[:k]
    return 1.0 if any(is_relevant_chunk(c, sources) for c in top) else 0.0


def recall_at_k(chunks: list[RetrievedChunk], expected: ExpectedSources, k: int) -> float:
    sources = parse_expected_sources(expected)
    if not sources:
        return 0.0
    top = chunks[:k]
    matched = 0
    for src in sources:
        if any(is_relevant_chunk(c, [src]) for c in top):
            matched += 1
    return matched / len(sources)


def precision_at_k(chunks: list[RetrievedChunk], expected: ExpectedSources, k: int) -> float:
    if k <= 0:
        return 0.0
    sources = parse_expected_sources(expected)
    top = chunks[:k]
    if not top:
        return 0.0
    relevant = sum(1 for c in top if is_relevant_chunk(c, sources))
    return relevant / len(top)


def mrr(chunks: list[RetrievedChunk], expected: ExpectedSources) -> float:
    sources = parse_expected_sources(expected)
    for rank, chunk in enumerate(chunks, start=1):
        if is_relevant_chunk(chunk, sources):
            return 1.0 / rank
    return 0.0


def compute_retrieval_metrics(
    chunks: list[RetrievedChunk],
    expected_sources: ExpectedSources,
    k_values: list[int] | None = None,
) -> dict[str, float]:
    k = 5
    return {
        "precision": precision_at_k(chunks, expected_sources, k),
        "recall": recall_at_k(chunks, expected_sources, k),
        "hit": hit_at_k(chunks, expected_sources, k),
        "mrr": mrr(chunks, expected_sources),
    }
