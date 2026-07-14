from unittest.mock import MagicMock, patch

from web_scrapper.embeddings import sparse_client as sparse_module
from web_scrapper.embeddings.sparse_client import get_sparse_embedding_client


def test_get_sparse_embedding_client_is_cached() -> None:
    sparse_module.get_sparse_embedding_client.cache_clear()
    with patch.object(sparse_module, "SparseEmbeddingClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        first = get_sparse_embedding_client("Qdrant/bm25")
        second = get_sparse_embedding_client("Qdrant/bm25")
    assert first is second
    mock_cls.assert_called_once_with(model_name="Qdrant/bm25")
