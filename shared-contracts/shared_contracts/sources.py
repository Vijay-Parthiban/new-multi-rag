from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class SourceRecordBase(BaseModel):
    name: str
    source_type: str = Field(..., description="e.g. minio, google_drive, s3, azure_blob, web_scraper")
    config: dict[str, Any] = Field(default_factory=dict)


class SourceRecordCreate(SourceRecordBase):
    pass


class SourceRecordRead(SourceRecordBase):
    id: uuid.UUID
    sync_status: str = "idle"
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
