"""Shared payload / search vocabulary for the RAG Qdrant contract."""
from __future__ import annotations

from typing import Literal

WEB_SCRAPE_SOURCE_TYPE = "web_scrape"
FILE_INGEST_SOURCE_TYPE = "file_ingest"

SourceTypeFilter = Literal["all", "web_scrape", "file_ingest"]
SearchMode = Literal["hybrid", "dense", "sparse"]

SOURCE_TYPE_FIELD = "source_type"
SOURCE_ID_FIELD = "source_id"
LEGACY_SCRAPE_JOB_ID_FIELD = "scrape_job_id"

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
