from __future__ import annotations

import math

from rag_shared.types import RetrievedChunk, RerankedChunk

from eval_core.retrieval_metrics import mrr
from eval_core.source_match import is_relevant_chunk


def ndcg_at_k(chunks: list[RetrievedChunk], expected: list[str], k: int) -> float:
    dcg = 0.0
    for i, chunk in enumerate(chunks[:k], start=1):
        rel = 1.0 if is_relevant_chunk(chunk, set(expected)) else 0.0
        dcg += rel / math.log2(i + 1)
    ideal_rels = sorted(
        [1.0 if is_relevant_chunk(c, set(expected)) else 0.0 for c in chunks],
        reverse=True,
    )[:k]
    idcg = sum(rel / math.log2(i + 1) for i, rel in enumerate(ideal_rels, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def kendall_tau_rank_correlation(
    before: list[RetrievedChunk],
    after: list[RerankedChunk],
) -> float | None:
    if not before or not after:
        return None
    id_to_before_rank = {c.id: i for i, c in enumerate(before)}
    shared = [c for c in after if c.id in id_to_before_rank]
    if len(shared) < 2:
        return None
    before_ranks = [id_to_before_rank[c.id] for c in shared]
    after_ranks = list(range(len(shared)))
    try:
        from scipy.stats import kendalltau

        result = kendalltau(before_ranks, after_ranks)
        return float(result.correlation) if result.correlation is not None else None
    except ImportError:
        return _simple_kendall(before_ranks, after_ranks)


def _simple_kendall(x: list[int], y: list[int]) -> float:
    n = len(x)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            sign_x = x[i] - x[j]
            sign_y = y[i] - y[j]
            if sign_x * sign_y > 0:
                concordant += 1
            elif sign_x * sign_y < 0:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 0.0


def compute_rerank_metrics(
    before: list[RetrievedChunk],
    after: list[RerankedChunk],
    expected_sources: list[str],
    k_values: list[int],
) -> dict[str, float | None]:
    mrr_before = mrr(before, expected_sources)
    mrr_after = mrr(after, expected_sources)
    primary_k = 5 if 5 in k_values else (k_values[0] if k_values else 5)
    metrics: dict[str, float | None] = {
        "mrr_before": mrr_before,
        "mrr_after": mrr_after,
        "mrr": mrr_after,
        "mrr_delta": mrr_after - mrr_before,
        "kendall_tau": kendall_tau_rank_correlation(before, after),
    }
    for k in k_values:
        metrics[f"ndcg_at_{k}"] = ndcg_at_k(after, expected_sources, k)
    metrics["ndcg"] = metrics.get(f"ndcg_at_{primary_k}")
    return metrics
