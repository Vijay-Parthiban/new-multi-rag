from __future__ import annotations

from typing import Protocol

from rag_shared.types import RetrievedChunk, RerankedChunk


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RerankedChunk]: ...
