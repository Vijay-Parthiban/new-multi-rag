import logging
import os
import uuid
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
SearchMode = Literal["hybrid", "dense", "sparse"]


class QdrantVectorStore:
    """Dense + sparse Qdrant store (compatible with web-scrapper collection schema)."""

    def __init__(self, *, url: str, collection: str, api_key: str | None = None) -> None:
        key = api_key or os.getenv("QDRANT_API_KEY") or "qdrant"
        self._client = QdrantClient(
            url=url, 
            api_key=key, 
            check_compatibility=False,
            timeout=60.0
        )
        self._collection = collection

    def ensure_collection(self, vector_size: int, *, enable_sparse: bool = True) -> None:
        if self._client.collection_exists(self._collection):
            info = self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            if isinstance(vectors, dict):
                dense = vectors.get(DENSE_VECTOR_NAME)
                if dense is None or dense.size != vector_size:
                    raise ValueError(
                        f"Collection {self._collection} dense vector size mismatch "
                        f"(expected {vector_size})"
                    )
                if enable_sparse:
                    sparse_vectors = info.config.params.sparse_vectors or {}
                    if SPARSE_VECTOR_NAME not in sparse_vectors:
                        raise ValueError(
                            f"Collection {self._collection} missing sparse vector '{SPARSE_VECTOR_NAME}'"
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
                DENSE_VECTOR_NAME: qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE)
            },
            sparse_vectors_config=sparse_vectors_config,
        )
        logger.info("qdrant_collection_created collection=%s size=%d", self._collection, vector_size)

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
        """Delete all points whose payload matches the given filter."""
        self._client.delete(
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
        if mode == "hybrid":
            if dense_vector is None or sparse_vector is None:
                raise ValueError("hybrid search requires both dense_vector and sparse_vector")
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
        return self._client.query_points(
            collection_name=self._collection,
            query=sparse_vector,
            using=SPARSE_VECTOR_NAME,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )

