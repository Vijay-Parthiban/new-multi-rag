import logging

from crawler_shared.config import Settings
from crawler_shared.types import SourceTypeFilter

from web_scrapper.embeddings.client import EmbeddingClient
from web_scrapper.embeddings.sparse_client import get_sparse_embedding_client
from web_scrapper.vector.filters import build_source_filter
from web_scrapper.vector.hit_mapper import map_scored_point
from web_scrapper.vector.qdrant_store import QdrantVectorStore, SearchMode

logger = logging.getLogger(__name__)


def search_scrape_chunks(
    settings: Settings,
    *,
    query_text: str,
    limit: int = 5,
    mode: SearchMode = "hybrid",
    source_type: SourceTypeFilter = "all",
    source_id: str | None = None,
) -> list[dict[str, object]]:
    """Run dense, sparse, or hybrid (RRF) retrieval against the scrape collection."""
    dense_vector = None
    sparse_vector = None

    if mode in {"dense", "hybrid"}:
        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )
        dense_vector = embedder.embed_text(query_text)

    if mode in {"sparse", "hybrid"}:
        sparse_embedder = get_sparse_embedding_client(settings.sparse_embedding_model)
        sparse_vector = sparse_embedder.embed(query_text)

    query_filter = build_source_filter(source_type=source_type, source_id=source_id)

    qdrant = QdrantVectorStore(url=settings.qdrant_url, collection=settings.qdrant_collection)
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
