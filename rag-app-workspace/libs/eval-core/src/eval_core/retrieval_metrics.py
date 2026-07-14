from __future__ import annotations

from rag_shared.types import RetrievedChunk

from eval_core.source_match import is_relevant_chunk


def hit_at_k(chunks: list[RetrievedChunk], expected: list[str], k: int) -> float:
    top = chunks[:k]
    return 1.0 if any(is_relevant_chunk(c, set(expected)) for c in top) else 0.0


def recall_at_k(chunks: list[RetrievedChunk], expected: list[str], k: int) -> float:
    if not expected:
        return 0.0
    top = chunks[:k]
    matched = 0
    for exp in expected:
        if any(is_relevant_chunk(c, {exp}) for c in top):
            matched += 1
    return matched / len(expected)


def precision_at_k(chunks: list[RetrievedChunk], expected: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = chunks[:k]
    relevant = sum(1 for c in top if is_relevant_chunk(c, set(expected)))
    return relevant / k


def mrr(chunks: list[RetrievedChunk], expected: list[str]) -> float:
    for rank, chunk in enumerate(chunks, start=1):
        if is_relevant_chunk(chunk, set(expected)):
            return 1.0 / rank
    return 0.0


def compute_retrieval_metrics(
    chunks: list[RetrievedChunk],
    expected_sources: list[str],
    k_values: list[int],
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for k in k_values:
        metrics[f"hit_at_{k}"] = hit_at_k(chunks, expected_sources, k)
        metrics[f"recall_at_{k}"] = recall_at_k(chunks, expected_sources, k)
        metrics[f"precision_at_{k}"] = precision_at_k(chunks, expected_sources, k)
    metrics["mrr"] = mrr(chunks, expected_sources)
    return metrics
