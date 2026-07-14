import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from qdrant_client.http import models as qmodels

from web_scrapper.embeddings.client import EmbeddingClient
from web_scrapper.embeddings.sparse_client import SparseEmbeddingClient

logger = logging.getLogger(__name__)


def embed_markdown_chunks_parallel(
    *,
    chunks: list[str],
    embedder: EmbeddingClient,
    sparse_embedder: SparseEmbeddingClient | None,
    max_workers: int,
) -> list[tuple[list[float], ...]]:
    """Embed markdown chunks with dense vectors and optional sparse vectors in parallel."""
    if not chunks:
        return []

    workers = max(1, min(max_workers, len(chunks)))
    results: list[tuple[list[float], ...] | None] = [None] * len(chunks)

    def _embed_chunk(index: int, text: str) -> tuple[int, tuple[list[float], ...]]:
        dense_vector = embedder.embed_passage(text)
        if sparse_embedder is None:
            return index, (dense_vector,)
        sparse_vector = sparse_embedder.embed(text)
        return index, (dense_vector, sparse_vector)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chunk-embed") as executor:
        futures = [executor.submit(_embed_chunk, idx, text) for idx, text in enumerate(chunks)]
        for future in as_completed(futures):
            index, vectors = future.result()
            results[index] = vectors

    completed = [results[i] for i in range(len(chunks))]
    logger.info("chunk_embeddings_completed chunks=%d workers=%d sparse=%s", len(completed), workers, sparse_embedder is not None)
    return completed
