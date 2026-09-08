from __future__ import annotations

from rag_shared.types import RetrievedChunk, RerankedChunk


class NoopReranker:
    model_name = "noop"

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RerankedChunk]:
        return [
            RerankedChunk(
                **chunk.model_dump(),
                rerank_score=chunk.retrieval_score,
            )
            for chunk in chunks[:top_k]
        ]
