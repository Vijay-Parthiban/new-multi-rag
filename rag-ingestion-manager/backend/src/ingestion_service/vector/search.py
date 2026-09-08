import logging

from src.shared.config.settings import get_settings
from src.ingestion_service.embeddings.client import EmbeddingClient
from src.ingestion_service.embeddings.sparse_client import get_sparse_embedding_client
from src.ingestion_service.vector.filters import build_source_filter
from src.ingestion_service.vector.hit_mapper import map_scored_point
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore, SearchMode

logger = logging.getLogger(__name__)


def search_document_chunks(
    *,
    query_text: str,
    collection: str | None = None,
    limit: int = 5,
    mode: SearchMode = "hybrid",
    source_type: str = "all",
    source_id: str | None = None,
    pipeline_id: str | None = None,
    file_id: str | None = None,
    directory_name: str | None = None,
    original_name: str | None = None,
    mime_type: str | None = None,
    rag_strategy: str | None = None,
) -> list[dict[str, object]]:
    """Run dense, sparse, or hybrid (RRF) retrieval against the vector database with metadata filtering."""
    settings = get_settings()
    collection_name = collection or settings.qdrant_collection

    dense_vector = None
    sparse_vector = None

    if mode in {"dense", "hybrid"}:
        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )
        dense_vector = embedder.embed_passage(query_text)

    if mode in {"sparse", "hybrid"}:
        sparse_embedder = get_sparse_embedding_client(settings.sparse_embedding_model)
        sparse_vector = sparse_embedder.embed(query_text)

    query_filter = build_source_filter(
        source_type=source_type,
        source_id=source_id,
        pipeline_id=pipeline_id,
        file_id=file_id,
        directory_name=directory_name,
        original_name=original_name,
        mime_type=mime_type,
        rag_strategy=rag_strategy,
    )

    qdrant = QdrantVectorStore(
        url=settings.qdrant_url,
        collection=collection_name,
        api_key=settings.qdrant_api_key,
    )
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
        "vector_search_completed collection=%s mode=%s source_type=%s source_id=%s query_len=%d hits=%d",
        collection_name,
        mode,
        source_type,
        source_id,
        len(query_text),
        len(results),
    )
    return results
