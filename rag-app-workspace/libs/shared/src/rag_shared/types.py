from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

WEB_SCRAPE_SOURCE_TYPE = "web_scrape"
FILE_INGEST_SOURCE_TYPE = "file_ingest"

SourceTypeFilter = Literal["all", "web_scrape", "file_ingest"]


class SourceType(StrEnum):
    WEB_SCRAPE = "web_scrape"
    FILE_INGEST = "file_ingest"


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    SPARSE = "sparse"


class ChunkPayload(BaseModel):
    source_type: str
    source_id: str
    source_locator: str
    type: str
    content: str
    chunk_index: int
    title: str | None = None
    scrape_job_id: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    id: str
    content: str
    source_type: str
    source_id: str
    source_locator: str
    chunk_index: int
    chunk_type: str
    title: str | None = None
    retrieval_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class RerankedChunk(RetrievedChunk):
    rerank_score: float
