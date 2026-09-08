"""Read-oriented Qdrant access wrapping the shared QdrantVectorStore."""
from __future__ import annotations

from qdrant_client.http import models as qmodels
from rag_shared.config import Settings

from platform_common.types import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from platform_common.vector.qdrant_store import QdrantVectorStore, SearchMode

__all__ = [
    "DENSE_VECTOR_NAME",
    "SPARSE_VECTOR_NAME",
    "QdrantStore",
    "SearchMode",
]


class QdrantStore:
    """Read-only Qdrant access for dense + sparse named vector search."""

    def __init__(self, settings: Settings, collection: str | None = None) -> None:
        self._store = QdrantVectorStore(
            url=settings.qdrant_url,
            collection=collection or settings.qdrant_collection,
            api_key=settings.qdrant_api_key,
        )

    def search(
        self,
        *,
        dense_vector: list[float] | None = None,
        sparse_vector: qmodels.SparseVector | None = None,
        limit: int = 5,
        mode: SearchMode = "hybrid",
        query_filter: qmodels.Filter | None = None,
    ) -> qmodels.QueryResponse:
        return self._store.search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=limit,
            mode=mode,
            query_filter=query_filter,
        )

    async def async_search(
        self,
        *,
        dense_vector: list[float] | None = None,
        sparse_vector: qmodels.SparseVector | None = None,
        limit: int = 5,
        mode: SearchMode = "hybrid",
        query_filter: qmodels.Filter | None = None,
    ) -> qmodels.QueryResponse:
        return await self._store.async_search(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            limit=limit,
            mode=mode,
            query_filter=query_filter,
        )
