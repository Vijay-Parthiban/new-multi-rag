"""Wire contracts for the Knowledge Products API.

These models mirror ``GET /api/knowledge-products`` and its item payload, which
the ingestion service serves. The retrieval service proxies that API, so the
field names here must match ``_product_to_dict`` in
``rag-ingestion-manager/backend/apps/api/routes/knowledge_products.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# The four destination engines the ingestion service supports.
SinkType = Literal["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
MonitorMode = Literal["live", "scheduled"]


class DestinationConfigInput(BaseModel):
    destination_type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDestinationConfigRead(BaseModel):
    id: uuid.UUID
    knowledge_product_id: uuid.UUID
    destination_type: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    status: str
    last_sync_at: datetime | None = None
    error_message: str | None = None

    class Config:
        from_attributes = True


class KnowledgeProductSourceRead(BaseModel):
    source_id: uuid.UUID
    name: str
    source_type: str | None = None
    connector_type: str | None = None
    minio_bucket: str | None = None
    status: str | None = None
    # The connector kwargs. The retrieval frontend reads this to show how a
    # source is configured, so it must survive the proxy.
    config: dict[str, Any] = Field(default_factory=dict)
    file_count: int = 0
    last_sync_at: datetime | None = None

    class Config:
        from_attributes = True


class KnowledgeProductPipelineRead(BaseModel):
    """One RAG pipeline attached to a product, as the ingestion API serializes it.

    The retrieval frontend renders the linked-pipeline list from this, so an
    absent entry shows up as an empty list on the Knowledge Store page.
    """

    id: uuid.UUID
    knowledge_product_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    rag_strategy: str
    embedding_model: str | None = None
    sparse_embedding_model: str | None = None
    modality: str | None = None
    directory_names: list[str] = Field(default_factory=list)
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    qdrant_collection: str | None = None
    web_scraper_enabled: bool = False
    scraper_seed_url: str | None = None
    scraper_max_depth: int | None = None
    scraper_max_pages: int | None = None
    scraper_mode: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class KnowledgeProductBase(BaseModel):
    name: str = Field(..., max_length=128)
    description: str | None = None
    enabled: bool = True
    monitor_mode: MonitorMode = "scheduled"
    sync_interval_seconds: int | None = None
    sync_interval_minutes: int | None = None


class KnowledgeProductCreate(KnowledgeProductBase):
    source_ids: list[str] = Field(default_factory=list)
    destinations: list[DestinationConfigInput] = Field(default_factory=list)


class KnowledgeProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    monitor_mode: MonitorMode | None = None
    sync_interval_seconds: int | None = None
    sync_interval_minutes: int | None = None
    source_ids: list[str] | None = None
    destinations: list[DestinationConfigInput] | None = None


class KnowledgeProductRead(KnowledgeProductBase):
    id: uuid.UUID
    status: str
    error_message: str | None = None
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    sources: list[KnowledgeProductSourceRead] = Field(default_factory=list)
    destinations: list[KnowledgeDestinationConfigRead] = Field(default_factory=list)
    # The resolved ingestion profile. The ingestion API reports the fallbacks the
    # fanout itself uses, so a product with no profile still answers here and the
    # UI never has to guess.
    ingestion_profile_id: str | None = None
    ingestion_profile_name: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_strategy: str = "recursive"
    modality_mode: str = "text"
    text_embedding_model: str | None = None
    caption_model: str | None = None
    image_min_pixels: int | None = None
    # The RAG pipelines that read this product. The Knowledge Store page shows
    # them as "Linked RAG Pipelines"; drop this and the count reads zero.
    pipelines: list[KnowledgeProductPipelineRead] = Field(default_factory=list)
    files_total: int = 0
    files_synced: int = 0
    files_pending: int = 0
    files_failed: int = 0
    pages_indexed: int = 0

    class Config:
        from_attributes = True
