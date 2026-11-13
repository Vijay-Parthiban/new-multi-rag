from __future__ import annotations

from typing import Any

from rag_shared.types import RetrievedChunk, RerankedChunk

from eval_core.retrieval_metrics import mrr, ndcg_at_k
from eval_core.source_match import ExpectedSource, is_relevant_chunk, parse_expected_sources


ExpectedSources = list[str] | list[ExpectedSource] | list[Any]


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
    expected_sources: ExpectedSources,
    k_values: list[int] | None = None,
) -> dict[str, float | None]:
    mrr_before = mrr(before, expected_sources)
    mrr_after = mrr(after, expected_sources)
    metrics: dict[str, float | None] = {
        "mrr_before": mrr_before,
        "mrr_after": mrr_after,
        "mrr": mrr_after,
        "mrr_delta": mrr_after - mrr_before,
        # `before` holds every retrieved chunk and `after` holds the top-k that reached the
        # model, so mrr_before and mrr_after are taken over different depths. The difference
        # then includes the plain truncation, and reading it as a reranker fault blames the
        # reranker for the retriever's low rank. This is the same measurement at the same
        # depth, which is the only pair a stage reading can compare.
        "mrr_before_at_k": mrr(before[: len(after)] or before, expected_sources),
        "kendall_tau": kendall_tau_rank_correlation(before, after),
        # Saved chat traces read this bare name as the k=5 value, so it stays.
        "ndcg": ndcg_at_k(after, expected_sources, 5),
    }
    for k in sorted({int(k) for k in (k_values or [5]) if int(k) > 0}):
        if k != 5:
            metrics[f"ndcg_at_{k}"] = ndcg_at_k(after, expected_sources, k)
    return metrics
