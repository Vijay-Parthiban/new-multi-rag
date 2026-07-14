import logging
from functools import lru_cache

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def get_sparse_embedding_client(model_name: str = "Qdrant/bm25") -> "SparseEmbeddingClient":
    """Return a process-wide cached sparse embedder (loads fastembed model once)."""
    return SparseEmbeddingClient(model_name=model_name)


class SparseEmbeddingClient:
    """BM25-style sparse embeddings for hybrid keyword + semantic search in Qdrant."""

    def __init__(self, *, model_name: str = "Qdrant/bm25") -> None:
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name)
        self._model_name = model_name
        logger.info("sparse_embedding_client_ready model=%s", model_name)

    def embed(self, text: str) -> qmodels.SparseVector:
        if not text.strip():
            return qmodels.SparseVector(indices=[], values=[])
        embedding = next(self._model.embed([text]))
        sparse = qmodels.SparseVector(
            indices=embedding.indices.tolist(),
            values=embedding.values.tolist(),
        )
        logger.info(
            "sparse_embedding_created model=%s terms=%d",
            self._model_name,
            len(sparse.indices),
        )
        return sparse
