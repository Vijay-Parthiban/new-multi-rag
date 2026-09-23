from __future__ import annotations

import time
from collections.abc import Iterator

from generation_core import Generator
from generation_core.prompt_builder import NO_SOURCES_ANSWER
from rag_shared.config import Settings
from reranker_core import Reranker, build_reranker
from retrieval_core import Retriever

from rag_core.schemas import (
    ChatResult,
    PipelineConfig,
    PipelineRequest,
    RerankResult,
    StreamEvent,
)


def _history_payload(cfg: PipelineConfig) -> list[dict[str, str]] | None:
    """Flatten the configured turns into the plain pairs the prompt builder takes.

    generation-core does not depend on rag-core, so the shared shape is a dict.
    """
    if not cfg.history:
        return None
    return [{"role": turn.role, "content": turn.content} for turn in cfg.history]


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
            strategy=cfg.strategy,
            stores=cfg.stores,
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

    def _effective_query(self, query: str, cfg: PipelineConfig) -> str:
        """Resolve a follow-up into a standalone question when the session has history.

        The rewritten question drives retrieval, rerank and the prompt, so all
        three agree on what was asked. An assistant with no history returns the
        question unchanged and pays nothing.
        """
        history = _history_payload(cfg)
        if not history:
            return query
        return self._generator.rewrite_query(query, history, model=cfg.generation_model)

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

        original_query = query
        query = self._effective_query(query, cfg)
        effective_query = query if query != original_query else None

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
            system_prompt=cfg.system_prompt,
            history=_history_payload(cfg),
            **cfg.sampling_kwargs(),
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
            effective_query=effective_query,
        )

    def stream_chat(
        self,
        query: str,
        *,
        config: PipelineConfig | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Yield status, token and done events for one chat turn.

        Same retrieve → rerank → generate sequence as ``chat``; the caller
        turns the events into server-sent event frames.
        """
        cfg = config or PipelineConfig()
        latency: dict[str, int] = {}
        total_start = time.perf_counter()

        if cfg.history:
            yield StreamEvent(type="status", message="Resolving the question against the session")
        stream_original_query = query
        query = self._effective_query(query, cfg)

        yield StreamEvent(type="status", message="Retrieving context")

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

        yield StreamEvent(type="status", message="Generating answer")

        t0 = time.perf_counter()
        parts: list[str] = []
        for delta in self._generator.generate_stream(
            query,
            reranked,
            model=cfg.generation_model,
            system_prompt=cfg.system_prompt,
            history=_history_payload(cfg),
            **cfg.sampling_kwargs(),
        ):
            parts.append(delta)
            yield StreamEvent(type="token", content=delta)
        answer = "".join(parts)

        latency["generate"] = int((time.perf_counter() - t0) * 1000)
        latency["total"] = int((time.perf_counter() - total_start) * 1000)

        yield StreamEvent(
            type="done",
            metadata={
                "answer": answer or NO_SOURCES_ANSWER,
                "sources": [
                    {
                        "source_locator": chunk.source_locator,
                        "chunk_index": chunk.chunk_index,
                        "rerank_score": chunk.rerank_score,
                    }
                    for chunk in reranked
                ],
                "retrieved_chunks": [chunk.model_dump() for chunk in retrieved],
                "reranked_chunks": [chunk.model_dump() for chunk in reranked],
                "latency_ms": latency,
                "route": "normal",
                "effective_query": query if query != stream_original_query else None,
            },
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
