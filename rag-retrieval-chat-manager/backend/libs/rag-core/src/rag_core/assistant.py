"""Resolve what a Knowledge Product's enabled destinations can serve.

An assistant pipeline reads a Knowledge Product's stores instead of owning a
Qdrant collection. Each RAG strategy names the store it reads, so the strategy
a pipeline may use is exactly the set its product's enabled destinations can
serve. This module is the one place that decides that, for both the API that
validates a pipeline and the retrieval path that reads it.
"""

from __future__ import annotations

from typing import Any

from rag_shared.types import KpDestination, KpStores, KpStrategy

from rag_core.session_memory import DEFAULT_TTL_S

STRATEGY_VECTOR = KpStrategy.VECTOR
STRATEGY_LEXICAL = KpStrategy.LEXICAL
STRATEGY_RELATIONAL = KpStrategy.RELATIONAL
STRATEGY_HYBRID = KpStrategy.HYBRID

DESTINATION_VECTOR = KpDestination.VECTOR
DESTINATION_LEXICAL = KpDestination.LEXICAL
DESTINATION_RELATIONAL = KpDestination.RELATIONAL

# Shown in the pipeline form, in this order.
STRATEGY_LABELS: dict[str, tuple[str, str]] = {
    KpStrategy.VECTOR: ("Vector search", "Qdrant dense vectors"),
    KpStrategy.LEXICAL: ("Keyword search", "OpenSearch BM25"),
    KpStrategy.RELATIONAL: ("SQL search", "PostgreSQL pgvector"),
    KpStrategy.HYBRID: ("Hybrid", "Vector and keyword, fused with reciprocal rank fusion"),
}

# A single-store strategy reads exactly this destination.
STRATEGY_DESTINATION: dict[str, str] = {
    KpStrategy.VECTOR: KpDestination.VECTOR,
    KpStrategy.LEXICAL: KpDestination.LEXICAL,
    KpStrategy.RELATIONAL: KpDestination.RELATIONAL,
}

# cache_redisvl is not here on purpose: it caches answers, it does not hold a
# retrievable copy of the chunks in a searchable form.
RETRIEVAL_DESTINATIONS: tuple[str, ...] = (
    KpDestination.VECTOR,
    KpDestination.LEXICAL,
    KpDestination.RELATIONAL,
)


# cache_redisvl is not a retrieval destination: it serves no strategy and holds no
# searchable copy of the chunks. It is read here for its namespace and its TTL, which
# is exactly what session memory needs.
SESSION_MEMORY_DESTINATION = "cache_redisvl"


class StrategyUnavailable(ValueError):
    """A chosen strategy needs a destination the product does not serve."""

    def __init__(self, strategy: str, missing: list[str]) -> None:
        self.strategy = strategy
        self.missing = missing
        super().__init__(
            f"The '{strategy}' strategy needs an enabled {', '.join(missing)} destination."
        )


def _enabled_types(destinations: list[dict[str, Any]]) -> set[str]:
    return {
        str(d.get("destination_type"))
        for d in destinations
        if d.get("enabled") and d.get("destination_type") in RETRIEVAL_DESTINATIONS
    }


def _config_for(destinations: list[dict[str, Any]], destination_type: str) -> dict[str, Any]:
    for d in destinations:
        if d.get("destination_type") == destination_type and d.get("enabled"):
            config = d.get("config")
            return config if isinstance(config, dict) else {}
    return {}


def session_memory_for_product(destinations: list[dict[str, Any]]) -> tuple[str, int] | None:
    """The Redis key prefix and TTL for session memory, or None when Redis is off.

    This is the whole gate for the feature. A product whose Redis destination is
    enabled gives every assistant of that product a session memory; a product
    without one keeps its assistants stateless.

    The prefix is the destination's own namespace, so one product's sessions can
    never collide with another's, and the TTL is the one the destination already
    carries.
    """
    config = _config_for(destinations, SESSION_MEMORY_DESTINATION)
    prefix = config.get("index_prefix")
    if not prefix:
        return None
    return str(prefix), int(config.get("ttl_seconds") or DEFAULT_TTL_S)


def strategies_for_product(destinations: list[dict[str, Any]]) -> list[str]:
    """The strategies this product's enabled destinations can serve."""
    enabled = _enabled_types(destinations)
    strategies: list[str] = []
    if KpDestination.VECTOR in enabled:
        strategies.append(KpStrategy.VECTOR)
    if KpDestination.LEXICAL in enabled:
        strategies.append(KpStrategy.LEXICAL)
    if KpDestination.RELATIONAL in enabled:
        strategies.append(KpStrategy.RELATIONAL)
    # Hybrid fuses the vector and the keyword ranking, so it needs both.
    if KpDestination.VECTOR in enabled and KpDestination.LEXICAL in enabled:
        strategies.append(KpStrategy.HYBRID)
    return strategies


def stores_for_product(destinations: list[dict[str, Any]]) -> KpStores:
    """The store names the fanout wrote this product's chunks to."""
    vector = _config_for(destinations, KpDestination.VECTOR)
    lexical = _config_for(destinations, KpDestination.LEXICAL)
    relational = _config_for(destinations, KpDestination.RELATIONAL)
    return KpStores(
        qdrant_collection=vector.get("collection_name"),
        opensearch_index=lexical.get("index_name"),
        pg_schema=relational.get("schema_name"),
        pg_table=relational.get("table_name") or "chunks",
    )


def resolve_strategy(strategy: str, stores: KpStores) -> None:
    """Raise StrategyUnavailable unless every store the strategy needs exists."""
    if strategy not in STRATEGY_LABELS:
        raise StrategyUnavailable(strategy, ["an unknown strategy"])
    missing: list[str] = []
    if strategy in (KpStrategy.VECTOR, KpStrategy.HYBRID) and not stores.qdrant_collection:
        missing.append(KpDestination.VECTOR)
    if strategy in (KpStrategy.LEXICAL, KpStrategy.HYBRID) and not stores.opensearch_index:
        missing.append(KpDestination.LEXICAL)
    if strategy == KpStrategy.RELATIONAL and not (stores.pg_schema and stores.pg_table):
        missing.append(KpDestination.RELATIONAL)
    if missing:
        raise StrategyUnavailable(strategy, missing)
