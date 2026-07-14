from __future__ import annotations

import time

from generation_core import Generator
from rag_shared.config import Settings
from reranker_core import Reranker, build_reranker
from retrieval_core import Retriever

from rag_core.schemas import ChatResult, PipelineConfig, PipelineRequest, RerankResult


class RAGPipeline:
    def __init__(
        self,
        settings: Settings,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever or Retriever(settings)
        self._generator = generator or Generator(settings)

    def with_reranker(self, enabled: bool, model: str | None = None) -> Reranker:
        return build_reranker(self._settings, enabled=enabled, model=model)

    def retrieve(
        self,
        query: str,
        *,
        config: PipelineConfig | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list:
        cfg = config or PipelineConfig()
        return self._retriever.retrieve(
            query,
            mode=cfg.retrieval_mode,
            limit=cfg.retrieve_limit,
            source_type=source_type,
            source_id=source_id,
            collection=cfg.collection,
            embedding_model=cfg.embedding_model,
            sparse_embedding_model=cfg.sparse_embedding_model,
        )

    def rerank(
        self,
        query: str,
        *,
        config: PipelineConfig | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> RerankResult:
        cfg = config or PipelineConfig()
        latency: dict[str, int] = {}
        total_start = time.perf_counter()

        t0 = time.perf_counter()
        retrieved = self.retrieve(
            query,
            config=cfg,
            source_type=source_type,
            source_id=source_id,
        )
        latency["retrieve"] = int((time.perf_counter() - t0) * 1000)

        reranker = self.with_reranker(cfg.rerank_enabled, cfg.rerank_model)
        t0 = time.perf_counter()
        reranked = reranker.rerank(query, retrieved, cfg.top_k)
        latency["rerank"] = int((time.perf_counter() - t0) * 1000)
        latency["total"] = int((time.perf_counter() - total_start) * 1000)

        return RerankResult(
            retrieved_chunks=retrieved,
            reranked_chunks=reranked,
            latency_ms=latency,
        )

    def from_request(self, body: PipelineRequest) -> tuple[PipelineConfig, str | None, str | None]:
        return body.to_config(), body.source_type, body.source_id

    def chat(
        self,
        query: str,
        *,
        config: PipelineConfig | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> ChatResult:
        cfg = config or PipelineConfig()
        latency: dict[str, int] = {}
        total_start = time.perf_counter()

        t0 = time.perf_counter()
        retrieved = self.retrieve(
            query,
            config=cfg,
            source_type=source_type,
            source_id=source_id,
        )
        latency["retrieve"] = int((time.perf_counter() - t0) * 1000)

        reranker = self.with_reranker(cfg.rerank_enabled, cfg.rerank_model)
        t0 = time.perf_counter()
        reranked = reranker.rerank(query, retrieved, cfg.top_k)
        latency["rerank"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        generation = self._generator.generate(
            query,
            reranked,
            model=cfg.generation_model,
            vision_model=cfg.vision_model,
            fusion_model=cfg.fusion_model,
        )
        latency.update(generation.latency_ms)
        latency["generate"] = generation.latency_ms.get("generate_total", 0)
        latency["total"] = int((time.perf_counter() - total_start) * 1000)

        return ChatResult(
            answer=generation.answer,
            retrieved_chunks=retrieved,
            reranked_chunks=reranked,
            latency_ms=latency,
            text_answer=generation.text_answer,
            vision_answer=generation.vision_answer,
            text_chunk_count=generation.text_chunk_count,
            image_chunk_count=generation.image_chunk_count,
        )

    def generate(
        self,
        query: str,
        *,
        config: PipelineConfig | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> ChatResult:
        return self.chat(
            query,
            config=config,
            source_type=source_type,
            source_id=source_id,
        )
