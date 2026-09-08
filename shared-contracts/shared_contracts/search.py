from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SearchHitContract(BaseModel):
    id: str
    score: float
    content: str
    source_type: str
    source_id: str
    source_locator: str
    chunk_index: int | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sink_origin: str = "qdrant"


class HybridRetrievalRequest(BaseModel):
    query: str
    limit: int = 10
    mode: Literal["hybrid", "dense", "sparse"] = "hybrid"
    source_type: str | None = None
    source_id: str | None = None
    collection: str | None = None
    dense_weight: float = 0.5
    sparse_weight: float = 0.5
