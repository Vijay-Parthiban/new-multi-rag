from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

SinkType = Literal["qdrant", "opensearch", "neo4j", "pgvector", "redisvl"]


class KnowledgeDestinationConfigBase(BaseModel):
    sink_type: SinkType
    destination_name: str
    connection_uri: str | None = None
    database_name: str | None = None
    collection_name: str | None = None
    is_active: bool = True
    config_metadata: dict[str, Any] | None = None


class KnowledgeDestinationConfigCreate(KnowledgeDestinationConfigBase):
    pass


class KnowledgeDestinationConfigRead(KnowledgeDestinationConfigBase):
    id: uuid.UUID
    knowledge_profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeProfileSourceRead(BaseModel):
    id: uuid.UUID
    knowledge_profile_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str | None = None
    source_type: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeProfileBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    fanout_mode: str = Field(default="all_sinks", description="Sync strategy: 'all_sinks' or 'selective'")
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)


class KnowledgeProfileCreate(KnowledgeProfileBase):
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    destinations: list[KnowledgeDestinationConfigCreate] = Field(default_factory=list)


class KnowledgeProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    fanout_mode: str | None = None
    sync_interval_minutes: int | None = None
    source_ids: list[uuid.UUID] | None = None
    destinations: list[KnowledgeDestinationConfigCreate] | None = None


class KnowledgeProfileRead(KnowledgeProfileBase):
    id: uuid.UUID
    sync_status: str
    last_synced_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    sources: list[KnowledgeProfileSourceRead] = Field(default_factory=list)
    destinations: list[KnowledgeDestinationConfigRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class TestConnectionRequest(BaseModel):
    sink_type: SinkType
    connection_uri: str | None = None
    collection_name: str | None = None
    database_name: str | None = None
    config_metadata: dict[str, Any] | None = None


class TestConnectionResponse(BaseModel):
    status: Literal["ok", "error"]
    sink_type: SinkType
    message: str
    details: dict[str, Any] | None = None
