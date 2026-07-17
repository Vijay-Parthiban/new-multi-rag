"""BM25-style sparse embeddings for hybrid search in Qdrant."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)


def _default_cache_dir() -> str:
    explicit = os.getenv("FASTEMBED_CACHE_PATH") or os.getenv("HF_HOME")
    if explicit:
        return explicit
    return str(Path.home() / ".cache" / "huggingface")


@lru_cache(maxsize=4)
def get_sparse_embedding_client(model_name: str = "Qdrant/bm25") -> SparseEmbeddingClient:
    """Return a process-wide cached sparse embedder (loads fastembed model once)."""
    return SparseEmbeddingClient(model_name=model_name)


class SparseEmbeddingClient:
    """BM25-style sparse embeddings for hybrid keyword + semantic search in Qdrant."""

    def __init__(self, *, model_name: str = "Qdrant/bm25", cache_dir: str | None = None) -> None:
        from fastembed import SparseTextEmbedding

        resolved_cache = cache_dir or _default_cache_dir()
        self._model = SparseTextEmbedding(model_name=model_name, cache_dir=resolved_cache)
        self._model_name = model_name
        logger.info(
            "sparse_embedding_client_ready model=%s cache_dir=%s",
            model_name,
            resolved_cache,
        )

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
