from __future__ import annotations

import math
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


def average_precision(chunks: list[RetrievedChunk], expected: ExpectedSources) -> float:
    """Mean precision at every rank that holds a relevant chunk, over the expected count.

    Relevance is chunk-level, like `precision_at_k`: one file can match several chunks and
    each match counts. A source that never appears stays in the denominator, which is what
    makes an unreachable source cost the score.
    """
    sources = parse_expected_sources(expected)
    if not sources:
        return 0.0
    hits = 0
    total = 0.0
    for rank, chunk in enumerate(chunks, start=1):
        if is_relevant_chunk(chunk, sources):
            hits += 1
            total += hits / rank
    return total / len(sources)


def ndcg_at_k(chunks: list[RetrievedChunk], expected: ExpectedSources, k: int) -> float:
    sources = parse_expected_sources(expected)
    dcg = 0.0
    for i, chunk in enumerate(chunks[:k], start=1):
        rel = 1.0 if is_relevant_chunk(chunk, sources) else 0.0
        dcg += rel / math.log2(i + 1)
    ideal_rels = sorted(
        [1.0 if is_relevant_chunk(c, sources) else 0.0 for c in chunks],
        reverse=True,
    )[:k]
    idcg = sum(rel / math.log2(i + 1) for i, rel in enumerate(ideal_rels, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def compute_retrieval_metrics(
    chunks: list[RetrievedChunk],
    expected_sources: ExpectedSources,
    k_values: list[int] | None = None,
) -> dict[str, float]:
    """Every ranking metric, scored at each requested k.

    The key carries its k, so a run holds recall@5 beside recall@10 rather than one reading
    whose depth the caller has to remember.
    """
    if not parse_expected_sources(expected_sources):
        # Without an expected source every ranking metric is undefined. An empty block is
        # honest; a zero would read as a retrieval failure.
        return {}

    ks = sorted({int(k) for k in (k_values or [5]) if int(k) > 0})
    metrics: dict[str, float] = {
        "mrr": mrr(chunks, expected_sources),
        "map": average_precision(chunks, expected_sources),
    }
    for k in ks:
        metrics[f"precision_at_{k}"] = precision_at_k(chunks, expected_sources, k)
        metrics[f"recall_at_{k}"] = recall_at_k(chunks, expected_sources, k)
        metrics[f"hit_at_{k}"] = hit_at_k(chunks, expected_sources, k)
        metrics[f"ndcg_at_{k}"] = ndcg_at_k(chunks, expected_sources, k)
    return metrics
