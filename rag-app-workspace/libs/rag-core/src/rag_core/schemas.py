from __future__ import annotations

from pydantic import BaseModel, Field

from rag_shared.types import RerankedChunk, RetrievedChunk, SearchMode


class PipelineConfig(BaseModel):
    retrieval_mode: SearchMode = SearchMode.HYBRID
    retrieve_limit: int = 20
    rerank_enabled: bool = True
    rerank_model: str | None = None
    top_k: int = 5
    generation_model: str | None = None
    vision_model: str | None = None
    fusion_model: str | None = None
    collection: str | None = None
    embedding_model: str | None = None
    sparse_embedding_model: str | None = None


class PipelineRequest(BaseModel):
    """Shared query-only request for retrieve → rerank → generate steps."""

    query: str = Field(..., description="The user question or search text.")
    source_type: str | None = Field(default=None, description="Optional source_type filter.")
    source_id: str | None = Field(default=None, description="Optional scrape/ingest job id filter.")
    retrieval_mode: SearchMode = SearchMode.HYBRID
    retrieve_limit: int = Field(default=20, ge=1, le=50)
    rerank_enabled: bool = True
    rerank_model: str | None = Field(default=None, description="Optional LiteLLM rerank model.")
    top_k: int = Field(default=5, ge=1, le=50)
    generation_model: str | None = Field(default=None, description="Optional LiteLLM text chat model.")
    vision_model: str | None = Field(default=None, description="Optional vision LLM for image chunks.")
    fusion_model: str | None = Field(default=None, description="Optional LLM to merge text and vision answers.")
    collection: str | None = Field(default=None, description="Optional collection override.")
    embedding_model: str | None = Field(default=None, description="Optional dense embedding model override.")
    sparse_embedding_model: str | None = Field(default=None, description="Optional sparse embedding model override.")

    def to_config(self) -> PipelineConfig:
        return PipelineConfig(
            retrieval_mode=self.retrieval_mode,
            retrieve_limit=self.retrieve_limit,
            rerank_enabled=self.rerank_enabled,
            rerank_model=self.rerank_model,
            top_k=self.top_k,
            generation_model=self.generation_model,
            vision_model=self.vision_model,
            fusion_model=self.fusion_model,
            collection=self.collection,
            embedding_model=self.embedding_model,
            sparse_embedding_model=self.sparse_embedding_model,
        )


class RerankResult(BaseModel):
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RerankedChunk]
    latency_ms: dict[str, int] = Field(default_factory=dict)


class ChatResult(BaseModel):
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RerankedChunk]
    latency_ms: dict[str, int] = Field(default_factory=dict)
    text_answer: str | None = None
    vision_answer: str | None = None
    text_chunk_count: int = 0
    image_chunk_count: int = 0
