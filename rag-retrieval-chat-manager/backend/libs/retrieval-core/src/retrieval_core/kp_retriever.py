"""Read a knowledge product's stores by strategy.

Each strategy reads one store, except hybrid, which reads the vector and the
keyword store and fuses the two rankings. The returned dicts all have the shape
``chunk_from_search_hit`` expects, so the caller gets ``RetrievedChunk`` objects
whichever strategy ran.
"""

from __future__ import annotations

import logging

from rag_shared.config import Settings
from rag_shared.types import KpStores, KpStrategy
from vector_core import search_scrape_chunks
from vector_core.lexical import search_lexical_index
from vector_core.relational import reciprocal_rank_fusion, search_pgvector_chunks

logger = logging.getLogger(__name__)

# Qdrant dense is the only vector search a fanout collection supports: the
# writer passes enable_sparse=False, so no product collection has sparse vectors.
_KP_VECTOR_MODE = "dense"


class KpRetriever:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def retrieve(
        self,
        query: str,
        *,
        strategy: str,
        stores: KpStores,
        limit: int,
        embedding_model: str | None = None,
    ) -> list[dict[str, object]]:
        if strategy == KpStrategy.VECTOR:
            return self._vector(query, stores, limit, embedding_model)
        if strategy == KpStrategy.LEXICAL:
            return search_lexical_index(
                self._settings,
                query_text=query,
                index_name=stores.opensearch_index or "",
                limit=limit,
            )
        if strategy == KpStrategy.RELATIONAL:
            return search_pgvector_chunks(
                self._settings,
                query_text=query,
                schema=stores.pg_schema,
                table=stores.pg_table,
                limit=limit,
                embedding_model=embedding_model,
            )
        if strategy == KpStrategy.HYBRID:
            # Ask each store for the same number, so neither ranking dominates
            # the fusion by being longer.
            vector_hits = self._vector(query, stores, limit, embedding_model)
            lexical_hits = search_lexical_index(
                self._settings,
                query_text=query,
                index_name=stores.opensearch_index or "",
                limit=limit,
            )
            return reciprocal_rank_fusion([vector_hits, lexical_hits], limit=limit)
        raise ValueError(f"Unknown strategy: {strategy}")

    def _vector(
        self,
        query: str,
        stores: KpStores,
        limit: int,
        embedding_model: str | None,
    ) -> list[dict[str, object]]:
        return search_scrape_chunks(
            self._settings,
            query_text=query,
            limit=limit,
            mode=_KP_VECTOR_MODE,
            source_type="all",
            collection=stores.qdrant_collection,
            embedding_model=embedding_model,
            qdrant_url=self._settings.qdrant_kp_url or self._settings.qdrant_url,
        )
