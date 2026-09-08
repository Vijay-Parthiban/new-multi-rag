from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class PipelineConfigContract(BaseModel):
    id: uuid.UUID | None = None
    name: str = "Default RAG Pipeline"
    description: str | None = None
    retrieval_mode: str = "hybrid"
    retrieve_limit: int = 10
    collection: str = "knowledge_qdrant_collection"
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    reranker_enabled: bool = True
    reranker_model: str = "cohere/rerank-english-v3.0"
    top_n_rerank: int = 5
    generator_model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_tokens: int = 1024


class RAGTraceContract(BaseModel):
    trace_id: uuid.UUID
    session_id: uuid.UUID
    message_id: uuid.UUID
    query: str
    answer: str
    retrieval_latency_ms: float
    rerank_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    sources_retrieved_count: int
    faithfulness_score: float | None = None
    answer_relevancy_score: float | None = None
    created_at: datetime
