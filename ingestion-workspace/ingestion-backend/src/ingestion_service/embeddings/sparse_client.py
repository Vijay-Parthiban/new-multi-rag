import logging
from functools import lru_cache

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def get_sparse_embedding_client(model_name: str = "Qdrant/bm25") -> "SparseEmbeddingClient":
    return SparseEmbeddingClient(model_name=model_name)


class SparseEmbeddingClient:
    def __init__(self, *, model_name: str = "Qdrant/bm25") -> None:
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name, cache_dir="/root/.cache/huggingface")
        self._model_name = model_name

    def embed(self, text: str) -> qmodels.SparseVector:
        if not text.strip():
            return qmodels.SparseVector(indices=[], values=[])
        embedding = next(self._model.embed([text]))
        return qmodels.SparseVector(
            indices=embedding.indices.tolist(),
            values=embedding.values.tolist(),
        )
