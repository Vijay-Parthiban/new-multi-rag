from platform_common.embeddings.dense import EmbeddingClient
from platform_common.embeddings.sparse import SparseEmbeddingClient, get_sparse_embedding_client

__all__ = [
    "EmbeddingClient",
    "SparseEmbeddingClient",
    "get_sparse_embedding_client",
]
