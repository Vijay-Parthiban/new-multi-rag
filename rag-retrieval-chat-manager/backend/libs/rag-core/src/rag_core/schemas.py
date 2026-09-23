from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from rag_shared.types import KpStores, RerankedChunk, RetrievedChunk, SearchMode


class SessionTurn(BaseModel):
    """One remembered turn of a session. Only the text is kept."""

    role: Literal["user", "assistant"]
    content: str


class ModelSettings(BaseModel):
    """Sampling settings for the model call.

    Every field is optional and unset means "use the value below me in the
    chain". Nothing here defaults to a real number, because a request that
    carried defaults would silently mask the pipeline it belongs to. The chain
    is request override -> pipeline settings -> service Settings.

    ``top_k`` here is the sampler's cutoff, and is a different thing from
    ``PipelineConfig.top_k``, which is how many reranked chunks reach the prompt.
    Many providers, OpenAI included, ignore a sampler top_k.
    """

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)


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
    system_prompt: str | None = None
    # Set by an assistant pipeline. A request that leaves them unset runs the
    # legacy scrape-collection path.
    strategy: str | None = None
    stores: KpStores | None = None
    # Earlier turns of this session, replayed ahead of the context message. Loaded
    # from the session memory, never from the request body: a caller that could
    # post its own history would bypass the session the pipeline owns.
    history: list[SessionTurn] = Field(default_factory=list)
    # Sampling settings for the answering call. Unset means the service
    # defaults in Settings apply, which is how every pipeline behaved before
    # this field existed.
    model_settings: ModelSettings | None = None

    def sampling_kwargs(self) -> dict[str, float | int | None]:
        """Sampling arguments for the answering call, ready to unpack.

        The generator falls back to Settings for any value left as None, so an
        unset field keeps the previous behaviour instead of forcing a value.
        """
        settings = self.model_settings or ModelSettings()
        return {
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "top_k": settings.top_k,
        }


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
    system_prompt: str | None = Field(
        default=None, description="Optional system message that replaces the built-in RAG prompt."
    )
    strategy: str | None = Field(
        default=None, description="Optional knowledge-product strategy: vector, lexical, relational, hybrid."
    )
    stores: KpStores | None = Field(
        default=None, description="Optional knowledge-product store names the strategy reads."
    )
    model_settings: ModelSettings | None = Field(
        default=None, description="Optional sampling settings that override the pipeline's."
    )

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
            system_prompt=self.system_prompt,
            strategy=self.strategy,
            stores=self.stores,
            model_settings=self.model_settings,
        )


class RerankResult(BaseModel):
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RerankedChunk]
    latency_ms: dict[str, int] = Field(default_factory=dict)


class StreamEvent(BaseModel):
    """One server-sent event from a streaming chat turn."""

    type: str  # "status" | "token" | "done" | "error"
    message: str | None = None
    content: str | None = None
    metadata: dict | None = None


class ChatResult(BaseModel):
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RerankedChunk]
    latency_ms: dict[str, int] = Field(default_factory=dict)
    text_answer: str | None = None
    vision_answer: str | None = None
    text_chunk_count: int = 0
    image_chunk_count: int = 0
    # The standalone question a session turn was rewritten into, or None when the
    # turn had no history and the question was searched as written.
    effective_query: str | None = None
