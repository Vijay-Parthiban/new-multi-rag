from qdrant_client.http import models as qmodels

from vector_core.sparse_client import SparseEmbeddingClient


def test_sparse_embedding_empty_text_returns_empty_vector() -> None:
    client = SparseEmbeddingClient.__new__(SparseEmbeddingClient)
    result = client.embed("")
    assert result == qmodels.SparseVector(indices=[], values=[])
