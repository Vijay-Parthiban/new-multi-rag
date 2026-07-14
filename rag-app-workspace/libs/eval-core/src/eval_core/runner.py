from __future__ import annotations

from dataclasses import dataclass

from generation_core import Generator
from rag_core import PipelineConfig, RAGPipeline
from rag_shared.chunk_utils import is_image_chunk, passage_text_for_chunk
from rag_shared.config import Settings
from rag_shared.types import RerankedChunk, RetrievedChunk
from reranker_core import build_reranker
from retrieval_core import Retriever

from eval_core.ragas_client import compute_generation_ragas_metrics, compute_retrieval_ragas_metrics
from eval_core.rerank_metrics import compute_rerank_metrics
from eval_core.retrieval_metrics import compute_retrieval_metrics


@dataclass
class GoldenItem:
    question: str
    ground_truth_answer: str | None
    expected_sources: list[str]
    label: str | None = None
    category: str | None = None


@dataclass
class EvalItemResult:
    retrieved_chunks: list[RetrievedChunk]
    retrieval_metrics: dict
    reranked_chunks: list[RerankedChunk]
    rerank_metrics: dict
    generated_answer: str
    generation_metrics: dict


class GoldenItemEvaluator:
    def __init__(self, settings: Settings, pipeline: RAGPipeline | None = None) -> None:
        self._settings = settings
        self._pipeline = pipeline or RAGPipeline(settings)
        self._retriever = Retriever(settings)
        self._generator = Generator(settings)

    def evaluate_item(
        self,
        item: GoldenItem,
        config: PipelineConfig,
        k_values: list[int] | None = None,
    ) -> EvalItemResult:
        k_values = k_values or [1, 3, 5, 10]

        retrieved = self._retriever.retrieve(
            item.question,
            mode=config.retrieval_mode,
            limit=config.retrieve_limit,
            collection=config.collection,
            embedding_model=config.embedding_model,
            sparse_embedding_model=config.sparse_embedding_model,
        )
        retrieval_metrics = compute_retrieval_metrics(
            retrieved, item.expected_sources, k_values
        )
        reference = (item.ground_truth_answer or "").strip()
        if reference:
            retrieval_metrics.update(
                compute_retrieval_ragas_metrics(
                    self._settings,
                    question=item.question,
                    contexts=[
                        passage_text_for_chunk(c) if is_image_chunk(c) else c.content
                        for c in retrieved
                    ],
                    reference=reference,
                    label=item.label,
                    category=item.category,
                )
            )

        reranker = build_reranker(
            self._settings,
            enabled=config.rerank_enabled,
            model=config.rerank_model,
        )
        reranked = reranker.rerank(item.question, retrieved, config.top_k)
        rerank_metrics = compute_rerank_metrics(
            retrieved, reranked, item.expected_sources, k_values
        )

        generation = self._generator.generate(
            item.question,
            reranked,
            model=config.generation_model,
            vision_model=config.vision_model,
            fusion_model=config.fusion_model,
        )
        contexts = [
            passage_text_for_chunk(c) if is_image_chunk(c) else c.content
            for c in reranked
        ]
        generation_metrics = compute_generation_ragas_metrics(
            self._settings,
            question=item.question,
            answer=generation.answer,
            contexts=contexts,
        )

        return EvalItemResult(
            retrieved_chunks=retrieved,
            retrieval_metrics=retrieval_metrics,
            reranked_chunks=reranked,
            rerank_metrics=rerank_metrics,
            generated_answer=generation.answer,
            generation_metrics=generation_metrics,
        )
