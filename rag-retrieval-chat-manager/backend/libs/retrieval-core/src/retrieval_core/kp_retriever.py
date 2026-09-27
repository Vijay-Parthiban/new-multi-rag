"""Read a knowledge product's stores by strategy.

Each retrieval mode reads one store, except hybrid, which reads the vector and the
keyword store and fuses the two rankings. A generation pattern reads whatever the
product can serve and lets the caller grade what comes back. The returned dicts all
have the shape ``chunk_from_search_hit`` expects, so the caller gets
``RetrievedChunk`` objects whichever strategy ran.
"""

from __future__ import annotations

import logging

from rag_shared.config import Settings
from rag_shared.types import AGENTIC_STRATEGIES, KpStores, KpStrategy
from vector_core import search_scrape_chunks
from vector_core.lexical import search_lexical_index
from vector_core.relational import reciprocal_rank_fusion

logger = logging.getLogger(__name__)

# Qdrant dense is the only vector search a fanout collection supports: the
# writer passes enable_sparse=False, so no product collection has sparse vectors.
_KP_VECTOR_MODE = "dense"


def _base_mode_for(stores: KpStores) -> str:
    """The retrieval mode a generation pattern runs on top of.

    Hybrid when both stores exist, because the grader is only as good as what it
    is handed and two rankings beat one. Otherwise whichever single store the
    product has, so a vector-only product still gets the patterns.
    """
    if stores.qdrant_collection and stores.opensearch_index:
        return KpStrategy.HYBRID
    if stores.qdrant_collection:
        return KpStrategy.VECTOR
    if stores.opensearch_index:
        return KpStrategy.LEXICAL
    raise ValueError("No retrieval store is configured for this product.")


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
        if strategy in AGENTIC_STRATEGIES:
            # The pattern is the caller's business; it only needs chunks.
            strategy = _base_mode_for(stores)
        if strategy == KpStrategy.VECTOR:
            return self._vector(query, stores, limit, embedding_model)
        if strategy == KpStrategy.LEXICAL:
            return search_lexical_index(
                self._settings,
                query_text=query,
                index_name=stores.opensearch_index or "",
                limit=limit,
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
