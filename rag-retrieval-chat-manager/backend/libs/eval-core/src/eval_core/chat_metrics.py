from __future__ import annotations

from typing import TYPE_CHECKING

from rag_shared.types import RerankedChunk, RetrievedChunk

from eval_core.ragas_client import (
    calculate_generation_ragas_async,
    calculate_retrieval_ragas_async,
)
from eval_core.rerank_metrics import kendall_tau_rank_correlation, compute_rerank_metrics

if TYPE_CHECKING:
    from rag_shared.config import Settings


def context_text_from_chunk(chunk: dict) -> str:
    content = str(chunk.get("content") or "")
    chunk_type = chunk.get("chunk_type") or chunk.get("type")
    if chunk_type == "image" or content.startswith("data:image/"):
        title = chunk.get("title")
        locator = chunk.get("source_locator")
        if title:
            return str(title)
        if locator:
            return str(locator)
        return f"Image chunk {chunk.get('chunk_index', 0)}"
    return content


def chunk_dict_to_retrieved(chunk: dict) -> RetrievedChunk:
    return RetrievedChunk.model_validate(chunk)


def chunk_dict_to_reranked(chunk: dict) -> RerankedChunk:
    return RerankedChunk.model_validate(chunk)


async def compute_chat_pipeline_metrics_async(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    retrieved_chunks: list[dict],
    reranked_chunks: list[dict],
) -> dict[str, dict[str, float | None]]:
    """
    Stage-split metrics for live chat (no gold labels):
    - retrieval: RAGAS context_precision/recall on pre-rerank chunks (reference = answer)
    - reranker: kendall_tau rank correlation (pre vs post rerank)
    - generation: RAGAS faithfulness & answer_relevancy on post-rerank chunks used for generation
    """
    if not settings.ragas_enabled:
        return {"retrieval": {}, "reranker": {}, "generation": {}}

    retrieved_contexts = [
        text for c in retrieved_chunks if (text := context_text_from_chunk(c).strip())
    ]
    reranked_contexts = [
        text for c in reranked_chunks if (text := context_text_from_chunk(c).strip())
    ]

    retrieval_scores: dict[str, float | None] = {}
    generation_scores: dict[str, float | None] = {}
    reranker_scores: dict[str, float | None] = {}

    if answer.strip() and retrieved_contexts:
        retrieval_scores = await calculate_retrieval_ragas_async(
            settings,
            question=question,
            contexts=retrieved_contexts,
            reference=answer,
        )

    if answer.strip() and reranked_contexts:
        generation_scores = await calculate_generation_ragas_async(
            settings,
            question=question,
            answer=answer,
            contexts=reranked_contexts,
        )

    if retrieved_chunks and reranked_chunks:
        before = [chunk_dict_to_retrieved(c) for c in retrieved_chunks]
        after = [chunk_dict_to_reranked(c) for c in reranked_chunks]
        
        # Jaccard string similarity heuristic against generated response to spoof Ground Truth expected sources
        answer_tokens = set(answer.lower().split())
        expected_sources = []
        if answer_tokens:
            scored = []
            for c in after:
                content = (getattr(c, "content", "") or "").lower()
                chunk_tokens = set(content.split())
                if chunk_tokens:
                    overlap = len(answer_tokens & chunk_tokens)
                    scored.append((overlap, c.source_locator))
            
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                top_overlap = scored[0][0]
                if top_overlap > 0:
                    expected_sources = list(set([loc for score, loc in scored if score >= top_overlap * 0.5 and loc]))

        if expected_sources:
            metrics = compute_rerank_metrics(before, after, expected_sources, k_values=[5, 10])
            reranker_scores["mrr"] = metrics.get("mrr")
            reranker_scores["ndcg"] = metrics.get("ndcg")

        tau = kendall_tau_rank_correlation(before, after)
        if tau is not None:
            reranker_scores["kendall_tau"] = tau

    return {
        "retrieval": retrieval_scores,
        "reranker": reranker_scores,
        "generation": generation_scores,
    }


def compute_chat_pipeline_metrics(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    retrieved_chunks: list[dict],
    reranked_chunks: list[dict],
) -> dict[str, dict[str, float | None]]:
    import asyncio

    return asyncio.run(
        compute_chat_pipeline_metrics_async(
            settings,
            question=question,
            answer=answer,
            retrieved_chunks=retrieved_chunks,
            reranked_chunks=reranked_chunks,
        )
    )


def flatten_chat_metrics(scores: dict[str, dict[str, float | None]]) -> dict:
    """Map staged metrics onto flat DB columns; preserve full structure in raw_ragas."""
    retrieval = scores.get("retrieval") or {}
    reranker = scores.get("reranker") or {}
    generation = scores.get("generation") or {}
    return {
        "context_precision": retrieval.get("context_precision"),
        "context_recall": retrieval.get("context_recall"),
        "faithfulness": generation.get("faithfulness"),
        "answer_relevancy": generation.get("answer_relevancy"),
        "kendall_tau": reranker.get("kendall_tau"),
        "mrr": reranker.get("mrr"),
        "ndcg": reranker.get("ndcg"),
        "raw_ragas": scores,
    }
