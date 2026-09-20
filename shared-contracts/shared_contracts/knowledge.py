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
    file_count: int = 0

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
    files_total: int = 0
    files_synced: int = 0
    files_pending: int = 0
    files_failed: int = 0
    pages_indexed: int = 0

    class Config:
        from_attributes = True
