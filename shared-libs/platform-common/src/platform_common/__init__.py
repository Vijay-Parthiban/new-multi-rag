"""Shared platform primitives used by ingestion, web-scrapper, and rag-app."""

from platform_common.auth import verify_api_key
from platform_common.embeddings import (
    EmbeddingClient,
    SparseEmbeddingClient,
    get_sparse_embedding_client,
)
from platform_common.ssrf import UnsafeURLError, validate_public_http_url
from platform_common.types import (
    FILE_INGEST_SOURCE_TYPE,
    WEB_SCRAPE_SOURCE_TYPE,
    SearchMode,
    SourceTypeFilter,
)

__all__ = [
    "EmbeddingClient",
    "FILE_INGEST_SOURCE_TYPE",
    "SparseEmbeddingClient",
    "UnsafeURLError",
    "WEB_SCRAPE_SOURCE_TYPE",
    "SearchMode",
    "SourceTypeFilter",
    "get_sparse_embedding_client",
    "validate_public_http_url",
    "verify_api_key",
]
