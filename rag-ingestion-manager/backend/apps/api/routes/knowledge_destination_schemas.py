"""Destination field schemas and default config builders for Knowledge Profiles."""

from __future__ import annotations

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


def _litellm_fields(settings: Settings) -> list[dict[str, Any]]:
    return [
        _field(
            "litellm_base_url",
            label="LiteLLM Base URL",
            description="OpenAI-compatible proxy base URL (Docker: http://host.docker.internal:4000)",
            placeholder=settings.litellm_base_url,
            group="LiteLLM",
        ),
        _field(
            "litellm_api_key",
            label="LiteLLM API Key",
            field_type="password",
            description="API key sent as Bearer token to LiteLLM",
            placeholder=settings.openai_api_key,
            group="LiteLLM",
        ),
    ]


def build_destination_types(settings: Settings) -> list[dict[str, Any]]:
    litellm = _litellm_fields(settings)
    return [
        {
            "id": "vector_qdrant",
            "name": "Qdrant",
            "category": "Vector Engine",
            "description": "Dense vector similarity search with HNSW indexing",
            "default_config": {
                "url": settings.qdrant_url,
                "api_key": settings.qdrant_api_key,
                "collection_name": "knowledge_qdrant_collection",
                "embedding_model": settings.embedding_model,
                "litellm_base_url": settings.litellm_base_url,
                "litellm_api_key": settings.openai_api_key,
                "vector_size": 2048,
                "distance": "Cosine",
                "hnsw_m": 16,
                "hnsw_ef_construct": 100,
                "quantization": "none",
                "on_disk_payload": True,
            },
            "fields": [
                *_litellm_fields(settings),
                _field("embedding_model", label="Embedding Model", field_type="model", model_kind="embedding", required=True, group="Embeddings", description="LiteLLM embedding model used during fanout"),
                _field("url", label="Qdrant URL", required=True, group="Connection"),
                _field("api_key", label="Qdrant API Key", field_type="password", group="Connection"),
                _field("collection_name", label="Collection Name", required=True, group="Collection"),
                _field("vector_size", label="Vector Dimensions", field_type="number", group="Collection", description="Expected embedding size; auto-detected from model output when mismatched"),
                _field("distance", label="Distance Metric", field_type="select", group="Collection", options=[{"value": "Cosine", "label": "Cosine"}, {"value": "Euclid", "label": "Euclid"}, {"value": "Dot", "label": "Dot"}]),
                _field("hnsw_m", label="HNSW M", field_type="number", group="HNSW Tuning", advanced=True, min_value=4, max_value=64),
                _field("hnsw_ef_construct", label="HNSW ef_construct", field_type="number", group="HNSW Tuning", advanced=True, min_value=32, max_value=512),
                _field("quantization", label="Quantization", field_type="select", group="HNSW Tuning", advanced=True, options=[{"value": "none", "label": "None"}, {"value": "int8_scalar", "label": "INT8 Scalar"}, {"value": "binary", "label": "Binary"}]),
                _field("on_disk_payload", label="Store Payload On Disk", field_type="boolean", group="Collection", advanced=True),
            ],
        },
        {
            "id": "lexical_opensearch",
            "name": "OpenSearch",
            "category": "Lexical & Sparse Search",
            "description": "BM25 lexical indexing with optional sparse model metadata",
            "default_config": {
                "endpoint_url": settings.opensearch_url,
                "index_name": "knowledge_lexical_index",
                "auth_type": "none",
                "username": "",
                "password": "",
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
                "sparse_model": settings.sparse_embedding_model,
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "1s",
            },
            "fields": [
                _field("endpoint_url", label="OpenSearch URL", required=True, group="Connection"),
                _field("index_name", label="Index Name", required=True, group="Index"),
                _field("auth_type", label="Authentication", field_type="select", group="Connection", options=[{"value": "none", "label": "None"}, {"value": "basic", "label": "Basic Auth"}]),
                _field("username", label="Username", group="Connection", advanced=True),
                _field("password", label="Password", field_type="password", group="Connection", advanced=True),
                _field("sparse_model", label="Sparse Model", field_type="model", model_kind="sparse", group="Lexical", description="Sparse model name stored in index metadata (LiteLLM / fastembed)"),
                _field("bm25_k1", label="BM25 k1", field_type="number", group="BM25 Tuning", advanced=True),
                _field("bm25_b", label="BM25 b", field_type="number", group="BM25 Tuning", advanced=True),
                _field("number_of_shards", label="Shards", field_type="number", group="Index", advanced=True, min_value=1),
                _field("number_of_replicas", label="Replicas", field_type="number", group="Index", advanced=True, min_value=0),
                _field("refresh_interval", label="Refresh Interval", group="Index", advanced=True, placeholder="1s"),
            ],
        },
        {
            "id": "graph_neo4j",
            "name": "Neo4j (GraphRAG)",
            "category": "Knowledge Graph Store",
            "description": "Document-chunk graph with optional LiteLLM entity extraction",
            "default_config": {
                "bolt_uri": settings.neo4j_bolt_uri,
                "http_url": settings.neo4j_http_url,
                "username": settings.neo4j_user,
                "password": settings.neo4j_password,
                "auth_disabled": settings.neo4j_auth_disabled,
                "database": "neo4j",
                "entity_extraction_enabled": False,
                "entity_extraction_model": "gpt-4o-mini",
                "litellm_base_url": settings.litellm_base_url,
                "litellm_api_key": settings.openai_api_key,
                "community_reports_enabled": False,
                "entity_resolution_mode": "exact_match",
                "max_entities_per_chunk": 10,
            },
            "fields": [
                *_litellm_fields(settings),
                _field("bolt_uri", label="Bolt URI", required=True, group="Connection"),
                _field("http_url", label="HTTP URL", group="Connection", description="Used by inspect/visualizer APIs"),
                _field("auth_disabled", label="Disable Authentication", field_type="boolean", group="Connection"),
                _field("username", label="Username", group="Connection"),
                _field("password", label="Password", field_type="password", group="Connection"),
                _field("database", label="Database", group="Connection"),
                _field("entity_extraction_enabled", label="Enable Entity Extraction", field_type="boolean", group="GraphRAG", description="Extract entities via LiteLLM and link Chunk->Entity nodes"),
                _field("entity_extraction_model", label="Entity Extraction Model", field_type="model", model_kind="chat", group="GraphRAG"),
                _field("max_entities_per_chunk", label="Max Entities / Chunk", field_type="number", group="GraphRAG", advanced=True, min_value=1, max_value=50),
                _field("community_reports_enabled", label="Community Reports", field_type="boolean", group="GraphRAG", advanced=True),
                _field("entity_resolution_mode", label="Entity Resolution", field_type="select", group="GraphRAG", advanced=True, options=[{"value": "exact_match", "label": "Exact Match"}, {"value": "fuzzy", "label": "Fuzzy"}, {"value": "llm", "label": "LLM-assisted"}]),
            ],
        },
        {
            "id": "relational_pgvector",
            "name": "PostgreSQL (pgvector)",
            "category": "Multi-Model Relational DB",
            "description": "Relational chunk storage with optional pgvector embeddings",
            "default_config": {
                "connection_url": settings.database_url.replace("+asyncpg", ""),
                "schema_name": "public",
                "table_name": "knowledge_chunks",
                "store_embeddings": True,
                "embedding_model": settings.embedding_model,
                "litellm_base_url": settings.litellm_base_url,
                "litellm_api_key": settings.openai_api_key,
                "vector_size": 2048,
                "index_algorithm": "hnsw",
                "distance_op": "vector_cosine_ops",
            },
            "fields": [
                *_litellm_fields(settings),
                _field("connection_url", label="PostgreSQL URL", required=True, group="Connection", description="postgresql://user:pass@host:5432/db"),
                _field("schema_name", label="Schema", group="Table"),
                _field("table_name", label="Table Name", required=True, group="Table"),
                _field("store_embeddings", label="Store Embeddings", field_type="boolean", group="Vectors", description="When enabled, stores pgvector column populated via LiteLLM embeddings"),
                _field("embedding_model", label="Embedding Model", field_type="model", model_kind="embedding", group="Vectors"),
                _field("vector_size", label="Vector Dimensions", field_type="number", group="Vectors"),
                _field("index_algorithm", label="Index Algorithm", field_type="select", group="Vectors", advanced=True, options=[{"value": "hnsw", "label": "HNSW"}, {"value": "ivfflat", "label": "IVFFlat"}, {"value": "none", "label": "None"}]),
                _field("distance_op", label="Distance Operator", field_type="select", group="Vectors", advanced=True, options=[{"value": "vector_cosine_ops", "label": "Cosine"}, {"value": "vector_l2_ops", "label": "L2"}, {"value": "vector_ip_ops", "label": "Inner Product"}]),
            ],
        },
        {
            "id": "cache_redisvl",
            "name": "RedisVL",
            "category": "Semantic Cache & Summary Store",
            "description": "Redis-backed chunk cache with optional LiteLLM summaries",
            "default_config": {
                "redis_url": settings.redis_url,
                "index_prefix": "knowledge_cache",
                "ttl_seconds": 86400,
                "similarity_threshold": 0.85,
                "embedding_model": settings.embedding_model,
                "litellm_base_url": settings.litellm_base_url,
                "litellm_api_key": settings.openai_api_key,
                "parent_child_mapping": True,
                "raptor_summaries": False,
                "summary_model": "gpt-4o-mini",
            },
            "fields": [
                *_litellm_fields(settings),
                _field("redis_url", label="Redis URL", required=True, group="Connection"),
                _field("index_prefix", label="Key Prefix", required=True, group="Cache"),
                _field("ttl_seconds", label="TTL (seconds)", field_type="number", group="Cache", min_value=60),
                _field("similarity_threshold", label="Semantic Similarity Threshold", field_type="number", group="Cache", description="Used when semantic dedup is enabled", min_value=0, max_value=1),
                _field("embedding_model", label="Cache Embedding Model", field_type="model", model_kind="embedding", group="Semantic Cache"),
                _field("parent_child_mapping", label="Parent-Child Mapping", field_type="boolean", group="Structure"),
                _field("raptor_summaries", label="RAPTOR Summaries", field_type="boolean", group="Summaries", description="Generate hierarchical summaries via LiteLLM"),
                _field("summary_model", label="Summary Model", field_type="model", model_kind="chat", group="Summaries"),
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
