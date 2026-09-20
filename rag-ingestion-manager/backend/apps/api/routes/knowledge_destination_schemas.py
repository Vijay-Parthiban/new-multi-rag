"""Destination field schemas, default config builders and store namespacing for Knowledge Products."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from src.shared.config.settings import Settings


def _field(
    key: str,
    *,
    label: str,
    field_type: str = "string",
    description: str = "",
    required: bool = False,
    group: str = "Connection",
    placeholder: str | None = None,
    model_kind: str | None = None,
    options: list[dict[str, str]] | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    advanced: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": field_type,
        "description": description,
        "required": required,
        "group": group,
        "placeholder": placeholder,
        "model_kind": model_kind,
        "options": options,
        "min": min_value,
        "max": max_value,
        "advanced": advanced,
    }


def build_destination_types(settings: Settings) -> list[dict[str, Any]]:
    return [
        {
            "id": "vector_qdrant",
            "name": "Qdrant",
            "category": "Vector Engine",
            "description": "Dense vector similarity search with HNSW indexing",
            "namespace_fields": ["collection_name"],
            "default_config": {
                "hnsw_m": 16,
                "hnsw_ef_construct": 100,
            },
            "fields": [
                _field("hnsw_m", label="HNSW M", field_type="number", group="HNSW Tuning", description="Edges per node. 16 matches the Qdrant default and suits most corpora.", min_value=4, max_value=64),
                _field("hnsw_ef_construct", label="HNSW ef_construct", field_type="number", group="HNSW Tuning", description="Build-time candidate list. 100 matches the Qdrant default and suits most corpora.", min_value=32, max_value=512),
            ],
        },
        {
            "id": "lexical_opensearch",
            "name": "OpenSearch",
            "category": "Lexical & Sparse Search",
            "description": "BM25 lexical indexing with optional sparse model metadata",
            "namespace_fields": ["index_name"],
            "default_config": {
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
                "sparse_model": settings.sparse_embedding_model,
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "1s",
            },
            "fields": [
                _field("sparse_model", label="Sparse Model", field_type="model", model_kind="sparse", group="Lexical", description="Recorded in the index metadata. The default is the fastembed BM25 model."),
                _field("bm25_k1", label="BM25 k1", field_type="number", group="BM25 Tuning", description="Term frequency saturation. 1.2 is the OpenSearch default and suits most text.", min_value=0),
                _field("bm25_b", label="BM25 b", field_type="number", group="BM25 Tuning", description="Length normalisation. 0.75 is the OpenSearch default and suits most text.", min_value=0, max_value=1),
                _field("number_of_shards", label="Shards", field_type="number", group="Index", advanced=True, description="1 suits a small corpus. Raise it for a corpus larger than a few GB.", min_value=1),
                _field("number_of_replicas", label="Replicas", field_type="number", group="Index", advanced=True, description="0 suits this single-node cluster. A replica would stay unassigned.", min_value=0),
                _field("refresh_interval", label="Refresh Interval", group="Index", advanced=True, description="1s is the OpenSearch default. Raise it to index faster.", placeholder="1s"),
            ],
        },
        {
            "id": "relational_pgvector",
            "name": "PostgreSQL (pgvector)",
            "category": "Multi-Model Relational DB",
            "description": "Relational chunk storage with optional pgvector embeddings",
            "namespace_fields": ["schema_name"],
            "default_config": {
                "table_name": "chunks",
                "store_embeddings": True,
            },
            "fields": [
                _field("store_embeddings", label="Store Embeddings", field_type="boolean", group="Vectors", description="On by default. The pgvector column carries the shared embedding model output."),
                _field("table_name", label="Table Name", required=True, group="Table", advanced=True, description="The schema already scopes this, so 'chunks' is safe for every product."),
            ],
        },
        {
            "id": "cache_redisvl",
            "name": "RedisVL",
            "category": "Semantic Cache & Summary Store",
            "description": "Redis-backed chunk cache with optional LiteLLM summaries",
            "namespace_fields": ["index_prefix"],
            "default_config": {
                "ttl_seconds": 86400,
                "similarity_threshold": 0.85,
                "parent_child_mapping": True,
                "raptor_summaries": False,
                "summary_model": settings.summary_model,
            },
            "fields": [
                _field("ttl_seconds", label="TTL (seconds)", field_type="number", group="Cache", description="86400 keeps a cached chunk for one day.", min_value=60),
                _field("similarity_threshold", label="Semantic Similarity Threshold", field_type="number", group="Cache", description="0.85 is a safe cosine cut-off for near-duplicate detection.", min_value=0, max_value=1),
                _field("parent_child_mapping", label="Parent-Child Mapping", field_type="boolean", group="Structure", description="On by default. Records the file-level parent key for every chunk."),
                _field("raptor_summaries", label="RAPTOR Summaries", field_type="boolean", group="Summaries", description="Off by default, because it calls the summary model once per file.", advanced=True),
                _field("summary_model", label="Summary Model", field_type="model", model_kind="chat", group="Summaries", description="Used only when RAPTOR Summaries is on.", advanced=True),
            ],
        },
    ]


def get_default_config(destination_type: str, settings: Settings) -> dict[str, Any]:
    for item in build_destination_types(settings):
        if item["id"] == destination_type:
            return deepcopy(item["default_config"])
    return {}


def merge_destination_config(destination_type: str, user_config: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    merged = get_default_config(destination_type, settings)
    if user_config:
        for key, value in user_config.items():
            if value is not None and value != "":
                merged[key] = value
    return merged


def normalize_destination_payload(destinations: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    known_ids = {item["id"] for item in build_destination_types(settings)}
    for dest in destinations:
        dest_type = dest.get("destination_type")
        if dest_type not in known_ids:
            continue
        normalized.append(
            {
                "destination_type": dest_type,
                "enabled": bool(dest.get("enabled", True)),
                "config": merge_destination_config(dest_type, dest.get("config") or {}, settings),
            }
        )
    return normalized


def namespace_fields_for(destination_type: str, settings: Settings) -> list[str]:
    """Config keys that make this destination's store unique. Empty if unknown."""
    for item in build_destination_types(settings):
        if item["id"] == destination_type:
            return list(item.get("namespace_fields") or [])
    return []


def slugify_product_name(name: str) -> str:
    """Lowercase a-z0-9 runs joined by '_', trimmed, max 32 chars.

    The result is safe inside a Postgres identifier, an OpenSearch index name
    and a Redis key prefix without quoting.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32].strip("_")
    return slug or "product"


def product_store_names(destination_type: str, slug: str, suffix: str) -> dict[str, str]:
    """Store names for one Knowledge Product on one destination.

    ``suffix`` is the first 8 hex characters of the product id, so two products
    with the same name still get different stores.
    """
    if destination_type in ("vector_qdrant", "lexical_opensearch"):
        key = "collection_name" if destination_type == "vector_qdrant" else "index_name"
        return {key: f"kp_{slug}_{suffix}"}
    if destination_type == "relational_pgvector":
        # The schema carries the identity. The table name is fixed and comes
        # from the catalogue default, so it is not a namespace field: two
        # products sharing one table name inside different schemas do not clash.
        return {"schema_name": f"kp_{slug}_{suffix}"}
    if destination_type == "cache_redisvl":
        return {"index_prefix": f"kp:{slug}:{suffix}"}
    return {}


def apply_store_namespace(
    destination_type: str,
    config: dict[str, Any],
    slug: str,
    suffix: str,
    settings: Settings,
) -> dict[str, Any]:
    """Assign the per-product store names to ``config``, overwriting any value.

    The store name is never user input, so the derived name always wins. A row
    written before the field was removed can hold a stale name, and keeping it
    would put two products in one store.
    """
    result = dict(config)
    names = product_store_names(destination_type, slug, suffix)
    for key in namespace_fields_for(destination_type, settings):
        if key in names:
            result[key] = names[key]
    return result
