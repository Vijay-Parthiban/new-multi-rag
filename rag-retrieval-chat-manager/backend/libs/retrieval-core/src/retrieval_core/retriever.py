from __future__ import annotations

from rag_shared.config import Settings
from rag_shared.types import KpStores, RetrievedChunk, SearchMode, SourceTypeFilter
from vector_core import search_scrape_chunks

from retrieval_core.hit_mapper import chunk_from_search_hit
from retrieval_core.kp_retriever import KpRetriever


class Retriever:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._kp = KpRetriever(settings)

    def retrieve(
        self,
        query: str,
        *,
        mode: SearchMode | None = None,
        limit: int | None = None,
        source_type: SourceTypeFilter | str | None = None,
        source_id: str | None = None,
        collection: str | None = None,
        embedding_model: str | None = None,
        sparse_embedding_model: str | None = None,
        strategy: str | None = None,
        stores: KpStores | None = None,
    ) -> list[RetrievedChunk]:
        resolved_limit = limit or self._settings.retrieve_limit

        # An assistant pipeline reads its knowledge product's stores. A request
        # with no strategy keeps the legacy scrape-collection path.
        if strategy and stores:
            hits = self._kp.retrieve(
                query,
                strategy=strategy,
                stores=stores,
                limit=resolved_limit,
                embedding_model=embedding_model,
            )
            return [chunk_from_search_hit(hit) for hit in hits]

        resolved_mode = (mode or self._settings.default_retrieval_mode).value
        resolved_source_type: SourceTypeFilter = (
            source_type if source_type in {"all", "web_scrape", "file_ingest"} else "all"
        )

        hits = search_scrape_chunks(
            self._settings,
            query_text=query,
            limit=resolved_limit,
            mode=resolved_mode,  # type: ignore[arg-type]
            source_type=resolved_source_type,
            source_id=source_id,
            collection=collection,
            embedding_model=embedding_model,
            sparse_embedding_model=sparse_embedding_model,
        )
        return [chunk_from_search_hit(hit) for hit in hits]
