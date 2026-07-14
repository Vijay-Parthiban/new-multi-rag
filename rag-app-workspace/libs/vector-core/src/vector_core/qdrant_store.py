from __future__ import annotations

import logging
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
SearchMode = Literal["hybrid", "dense", "sparse"]


class QdrantStore:
    """Read-only Qdrant access for dense + sparse named vector search."""

    def __init__(self, settings: Settings, collection: str | None = None) -> None:
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            check_compatibility=False,
        )
        self._collection = collection or settings.qdrant_collection

    def search(
        self,
        *,
        dense_vector: list[float] | None = None,
        sparse_vector: qmodels.SparseVector | None = None,
        limit: int = 5,
        mode: SearchMode = "hybrid",
        query_filter: qmodels.Filter | None = None,
    ) -> qmodels.QueryResponse:
        from qdrant_client.http.exceptions import UnexpectedResponse

        if mode == "hybrid":
            if dense_vector is None or sparse_vector is None:
                raise ValueError("hybrid search requires both dense_vector and sparse_vector")
            try:
                return self._client.query_points(
                    collection_name=self._collection,
                    prefetch=[
                        qmodels.Prefetch(
                            query=dense_vector,
                            using=DENSE_VECTOR_NAME,
                            limit=max(limit * 2, limit),
                            filter=query_filter,
                        ),
                        qmodels.Prefetch(
                            query=sparse_vector,
                            using=SPARSE_VECTOR_NAME,
                            limit=max(limit * 2, limit),
                            filter=query_filter,
                        ),
                    ],
                    query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
            except UnexpectedResponse as e:
                if e.status_code == 400 and "sparse" in str(e.content):
                    logger.warning(
                        "Collection %s does not support sparse vectors. Falling back to dense-only search.",
                        self._collection,
                    )
                    return self._client.query_points(
                        collection_name=self._collection,
                        query=dense_vector,
                        using=DENSE_VECTOR_NAME,
                        limit=limit,
                        query_filter=query_filter,
                        with_payload=True,
                        with_vectors=False,
                    )
                raise

        if mode == "dense":
            if dense_vector is None:
                raise ValueError("dense search requires dense_vector")
            return self._client.query_points(
                collection_name=self._collection,
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )

        if sparse_vector is None:
            raise ValueError("sparse search requires sparse_vector")
        try:
            return self._client.query_points(
                collection_name=self._collection,
                query=sparse_vector,
                using=SPARSE_VECTOR_NAME,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
        except UnexpectedResponse as e:
            if e.status_code == 400 and "sparse" in str(e.content):
                logger.warning(
                    "Collection %s does not support sparse vectors. Sparse search failed, returning empty points list.",
                    self._collection,
                )
                return qmodels.QueryResponse(points=[])
            raise
