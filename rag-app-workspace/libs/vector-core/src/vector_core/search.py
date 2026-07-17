from __future__ import annotations

import logging

from rag_shared.config import Settings
from rag_shared.types import SourceTypeFilter

from vector_core.embedding_client import EmbeddingClient
from vector_core.filters import build_source_filter
from vector_core.hit_mapper import map_scored_point
from vector_core.qdrant_store import QdrantStore, SearchMode
from vector_core.sparse_client import get_sparse_embedding_client

logger = logging.getLogger(__name__)


def search_scrape_chunks(
    settings: Settings,
    *,
    query_text: str,
    limit: int = 5,
    mode: SearchMode = "hybrid",
    source_type: SourceTypeFilter = "all",
    source_id: str | None = None,
    collection: str | None = None,
    embedding_model: str | None = None,
    sparse_embedding_model: str | None = None,
) -> list[dict[str, object]]:
    """Run dense, sparse, or hybrid (RRF) retrieval against the scrape collection."""
    dense_vector = None
    sparse_vector = None

    if mode in {"dense", "hybrid"}:
        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=embedding_model or settings.embedding_model,
        )
        dense_vector = embedder.embed_text(query_text)

    if mode in {"sparse", "hybrid"}:
        sparse_embedder = get_sparse_embedding_client(sparse_embedding_model or settings.sparse_embedding_model)
        sparse_vector = sparse_embedder.embed(query_text)

    query_filter = build_source_filter(source_type=source_type, source_id=source_id)

    qdrant = QdrantStore(settings, collection=collection)
    response = qdrant.search(
        dense_vector=dense_vector,
        sparse_vector=sparse_vector,
        limit=limit,
        mode=mode,
        query_filter=query_filter,
    )

    results: list[dict[str, object]] = []
    for hit in response.points:
        payload = hit.payload or {}
        if not payload:
            continue
        results.append(map_scored_point(hit))

    logger.info(
        "vector_search_completed mode=%s source_type=%s source_id=%s query_len=%d hits=%d",
        mode,
        source_type,
        source_id,
        len(query_text),
        len(results),
    )
    return results


async def search_scrape_chunks_async(
    settings: Settings,
    *,
    query_text: str,
    limit: int = 5,
    mode: SearchMode = "hybrid",
    source_type: SourceTypeFilter = "all",
    source_id: str | None = None,
    collection: str | None = None,
    embedding_model: str | None = None,
    sparse_embedding_model: str | None = None,
) -> list[dict[str, object]]:
    """Async version — runs embedding + Qdrant I/O off the event loop."""
    import asyncio

    dense_vector = None
    sparse_vector = None

    if mode in {"dense", "hybrid"}:
        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=embedding_model or settings.embedding_model,
        )
        dense_vector = await asyncio.to_thread(embedder.embed_text, query_text)

    if mode in {"sparse", "hybrid"}:
        sparse_embedder = get_sparse_embedding_client(sparse_embedding_model or settings.sparse_embedding_model)
        sparse_vector = await asyncio.to_thread(sparse_embedder.embed, query_text)

    query_filter = build_source_filter(source_type=source_type, source_id=source_id)

    qdrant = QdrantStore(settings, collection=collection)
    response = await qdrant.async_search(
        dense_vector=dense_vector,
        sparse_vector=sparse_vector,
        limit=limit,
        mode=mode,
        query_filter=query_filter,
    )

    results: list[dict[str, object]] = []
    for hit in response.points:
        payload = hit.payload or {}
        if not payload:
            continue
        results.append(map_scored_point(hit))

    logger.info(
        "async_vector_search_completed mode=%s source_type=%s source_id=%s query_len=%d hits=%d",
        mode,
        source_type,
        source_id,
        len(query_text),
        len(results),
    )
    return results
