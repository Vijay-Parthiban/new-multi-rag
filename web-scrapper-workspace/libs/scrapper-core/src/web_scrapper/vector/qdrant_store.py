import logging
import os
import uuid
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
if not QDRANT_API_KEY:
    raise ValueError("QDRANT_API_KEY is not set")

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
SearchMode = Literal["hybrid", "dense", "sparse"]


class QdrantVectorStore:
    """Persist scrape embeddings in Qdrant with dense + sparse named vectors."""

    def __init__(self, *, url: str, collection: str) -> None:
        self._client = QdrantClient(url=url, api_key=QDRANT_API_KEY, check_compatibility=False)
        self._collection = collection

    @property
    def client(self) -> QdrantClient:
        """Expose the raw client safely for administrative operations."""
        return self._client

    def ensure_collection(self, vector_size: int, *, enable_sparse: bool = True) -> None:
        if self._client.collection_exists(self._collection):
            info = self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            if isinstance(vectors, dict):
                dense = vectors.get(DENSE_VECTOR_NAME)
                if dense is None:
                    raise ValueError(
                        f"Qdrant collection {self._collection} is missing named vector '{DENSE_VECTOR_NAME}'"
                    )
                if dense.size != vector_size:
                    raise ValueError(
                        f"Qdrant collection {self._collection} dense size {dense.size} "
                        f"does not match embedding size {vector_size}"
                    )
                if enable_sparse:
                    sparse_vectors = info.config.params.sparse_vectors or {}
                    if SPARSE_VECTOR_NAME not in sparse_vectors:
                        raise ValueError(
                            f"Qdrant collection {self._collection} is missing sparse vector "
                            f"'{SPARSE_VECTOR_NAME}'. Recreate the collection to enable sparse search."
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

        vectors_config: qmodels.VectorParams | dict[str, qmodels.VectorParams] = {
            DENSE_VECTOR_NAME: qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        }
        sparse_vectors_config = None
        if enable_sparse:
            sparse_vectors_config = {
                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                    modifier=qmodels.Modifier.IDF,
                )
            }

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=vectors_config,
            sparse_vectors_config=sparse_vectors_config,
        )
        logger.info(
            "qdrant_collection_created collection=%s dense_size=%d sparse=%s",
            self._collection,
            vector_size,
            enable_sparse,
        )

    def upsert_batch(self, points_data: list[dict[str, object]]) -> None:
        """Batch upsert with optional dense and sparse named vectors per point."""
        points = []
        for item in points_data:
            raw_id = str(item["point_id"])
            deterministic_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))
            vector_payload: dict[str, object] = {}
            if item.get("dense_vector") is not None:
                vector_payload[DENSE_VECTOR_NAME] = item["dense_vector"]
            if item.get("sparse_vector") is not None:
                vector_payload[SPARSE_VECTOR_NAME] = item["sparse_vector"]
            if not vector_payload:
                raise ValueError("Each point must include at least one vector payload")

            points.append(
                qmodels.PointStruct(
                    id=deterministic_uuid,
                    vector=vector_payload,  # type: ignore[arg-type]
                    payload=item["payload"],  # type: ignore[arg-type]
                )
            )

        if points:
            self._client.upsert(
                collection_name=self._collection,
                points=points,
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
