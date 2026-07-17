"""Unified dense + sparse Qdrant store for ingest and retrieval."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Literal

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from platform_common.types import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME

logger = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "dense", "sparse"]


class QdrantVectorStore:
    """Persist and search embeddings with named dense + sparse vectors.

    Compatible with the shared scrape_embeddings collection contract used by
    web-scrapper (write), ingestion (write), and rag-app (read).
    """

    def __init__(
        self,
        *,
        url: str,
        collection: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        require_api_key: bool = False,
    ) -> None:
        key = api_key if api_key is not None else os.getenv("QDRANT_API_KEY")
        if require_api_key and not key:
            raise ValueError("QDRANT_API_KEY is not set")
        key = key or "qdrant"

        self._url = url
        self._api_key = key
        self._collection = collection
        self._timeout = timeout
        self._client = QdrantClient(
            url=url,
            api_key=key,
            check_compatibility=False,
            timeout=timeout,
        )
        self._async_client: AsyncQdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        return self._client

    @property
    def collection(self) -> str:
        return self._collection

    def _get_async_client(self) -> AsyncQdrantClient:
        if self._async_client is None:
            self._async_client = AsyncQdrantClient(
                url=self._url,
                api_key=self._api_key,
                check_compatibility=False,
                timeout=self._timeout,
            )
        return self._async_client

    def ensure_collection(self, vector_size: int, *, enable_sparse: bool = True) -> None:
        if self._client.collection_exists(self._collection):
            info = self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            if isinstance(vectors, dict):
                dense = vectors.get(DENSE_VECTOR_NAME)
                if dense is None:
                    raise ValueError(
                        f"Qdrant collection {self._collection} is missing named vector "
                        f"'{DENSE_VECTOR_NAME}'"
                    )
                if dense.size != vector_size:
                    raise ValueError(
                        f"Collection {self._collection} dense vector size mismatch "
                        f"(expected {vector_size}, got {dense.size})"
                    )
                if enable_sparse:
                    sparse_vectors = info.config.params.sparse_vectors or {}
                    if SPARSE_VECTOR_NAME not in sparse_vectors:
                        logger.warning(
                            "Collection %s missing sparse vector '%s'; auto-adding...",
                            self._collection,
                            SPARSE_VECTOR_NAME,
                        )
                        self._client.update_collection(
                            collection_name=self._collection,
                            sparse_vectors_config={
                                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                                    modifier=qmodels.Modifier.IDF
                                )
                            },
                        )
            else:
                if vectors.size != vector_size:
                    raise ValueError(
                        f"Qdrant collection {self._collection} vector size {vectors.size} "
                        f"does not match embedding size {vector_size}"
                    )
                if enable_sparse:
                    raise ValueError(
                        f"Qdrant collection {self._collection} uses a legacy single-vector schema. "
                        "Delete it or use a new QDRANT_COLLECTION name to store sparse vectors."
                    )
            return

        sparse_vectors_config = None
        if enable_sparse:
            sparse_vectors_config = {
                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(modifier=qmodels.Modifier.IDF)
            }

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                DENSE_VECTOR_NAME: qmodels.VectorParams(
                    size=vector_size, distance=qmodels.Distance.COSINE
                )
            },
            sparse_vectors_config=sparse_vectors_config,
        )
        logger.info(
            "qdrant_collection_created collection=%s size=%d sparse=%s",
            self._collection,
            vector_size,
            enable_sparse,
        )

    def upsert_batch(self, points_data: list[dict[str, object]]) -> None:
        points = []
        for item in points_data:
            raw_id = str(item["point_id"])
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))
            vector_payload: dict[str, object] = {}
            if item.get("dense_vector") is not None:
                vector_payload[DENSE_VECTOR_NAME] = item["dense_vector"]
            if item.get("sparse_vector") is not None:
                vector_payload[SPARSE_VECTOR_NAME] = item["sparse_vector"]
            if not vector_payload:
                raise ValueError("Each point must include at least one vector")

            points.append(
                qmodels.PointStruct(
                    id=point_uuid,
                    vector=vector_payload,  # type: ignore[arg-type]
                    payload=item["payload"],  # type: ignore[arg-type]
                )
            )

        if points:
            self._client.upsert(collection_name=self._collection, points=points)

    def delete_by_filter(self, payload_filter: qmodels.Filter) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(filter=payload_filter),
        )

    async def async_delete_by_filter(self, payload_filter: qmodels.Filter) -> None:
        client = self._get_async_client()
        await client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(filter=payload_filter),
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
        return self._do_search(
            self._client, dense_vector, sparse_vector, limit, mode, query_filter
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
        client = self._get_async_client()
        return await self._do_search_async(
            client, dense_vector, sparse_vector, limit, mode, query_filter
        )

    def _do_search(
        self,
        client: QdrantClient,
        dense_vector: list[float] | None,
        sparse_vector: qmodels.SparseVector | None,
        limit: int,
        mode: SearchMode,
        query_filter: qmodels.Filter | None,
    ) -> qmodels.QueryResponse:
        if mode == "hybrid":
            if dense_vector is None or sparse_vector is None:
                raise ValueError("hybrid search requires both dense_vector and sparse_vector")
            try:
                return client.query_points(
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
                        "Collection %s: sparse not supported, falling back to dense.",
                        self._collection,
                    )
                    return client.query_points(
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
            return client.query_points(
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
            return client.query_points(
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
                    "Collection %s: sparse search failed, returning empty.", self._collection
                )
                return qmodels.QueryResponse(points=[])
            raise

    async def _do_search_async(
        self,
        client: AsyncQdrantClient,
        dense_vector: list[float] | None,
        sparse_vector: qmodels.SparseVector | None,
        limit: int,
        mode: SearchMode,
        query_filter: qmodels.Filter | None,
    ) -> qmodels.QueryResponse:
        if mode == "hybrid":
            if dense_vector is None or sparse_vector is None:
                raise ValueError("hybrid search requires both dense_vector and sparse_vector")
            try:
                return await client.query_points(
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
                        "Collection %s: sparse not supported, falling back to dense.",
                        self._collection,
                    )
                    return await client.query_points(
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
            return await client.query_points(
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
            return await client.query_points(
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
                    "Collection %s: sparse search failed, returning empty.", self._collection
                )
                return qmodels.QueryResponse(points=[])
            raise
