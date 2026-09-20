from apps.api.routes.knowledge_destination_schemas import (
    apply_store_namespace,
    build_destination_types,
    merge_destination_config,
    normalize_destination_payload,
    product_store_names,
    slugify_product_name,
)
from src.shared.config.settings import Settings


def test_build_destination_types_includes_field_schemas() -> None:
    settings = Settings()
    destinations = build_destination_types(settings)
    assert len(destinations) == 4
    assert {item["id"] for item in destinations} == {
        "vector_qdrant",
        "lexical_opensearch",
        "relational_pgvector",
        "cache_redisvl",
    }
    assert "graph_neo4j" not in {item["id"] for item in destinations}
    qdrant = next(item for item in destinations if item["id"] == "vector_qdrant")
    assert any(field["key"] == "hnsw_m" for field in qdrant["fields"])

    # No connection or secret value is a field: the environment holds them.
    banned = {
        "url",
        "api_key",
        "endpoint_url",
        "connection_url",
        "redis_url",
        "litellm_base_url",
        "litellm_api_key",
        "username",
        "password",
        "auth_type",
        "vector_size",
        "collection_name",
        "index_name",
        "schema_name",
        "index_prefix",
    }
    for item in destinations:
        keys = {field["key"] for field in item["fields"]}
        assert not (keys & banned), f"{item['id']} still exposes {sorted(keys & banned)}"
        # Every default key is a real field, so no orphan default can be edited
        # by nothing.
        assert set(item["default_config"]) <= keys | {"table_name"}, item["id"]
        assert item["namespace_fields"], f"{item['id']} declares no namespace_fields"


def test_product_store_names_are_unique_per_product() -> None:
    assert slugify_product_name("My Res!") == "my_res"
    assert slugify_product_name("***") == "product"
    assert len(slugify_product_name("A" * 50)) == 32

    first = {
        dest: product_store_names(dest, "alpha", "1f2a3dcf")
        for dest in ["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
    }
    second = {
        dest: product_store_names(dest, "alpha", "deadbeef")
        for dest in ["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
    }
    for dest, names in first.items():
        assert names != second[dest], f"{dest} shares a store name across products"
    assert first["vector_qdrant"]["collection_name"].startswith("kp_")
    assert first["cache_redisvl"]["index_prefix"].startswith("kp:")


def test_apply_store_namespace_assigns_the_product_store() -> None:
    settings = Settings()

    # A profile config carries no store name at all.
    profile_cfg = merge_destination_config("vector_qdrant", {}, settings)
    assert "collection_name" not in profile_cfg

    # The product copy assigns one.
    renamed = apply_store_namespace("vector_qdrant", profile_cfg, "alpha", "1f2a3dcf", settings)
    assert renamed["collection_name"] == "kp_alpha_1f2a3dcf"

    # A stale name from a row written before the field was removed is replaced.
    stale = apply_store_namespace(
        "vector_qdrant", {"collection_name": "my_custom_coll"}, "alpha", "1f2a3dcf", settings
    )
    assert stale["collection_name"] == "kp_alpha_1f2a3dcf"

    # Postgres gets its own schema. The table name is fixed, because the schema
    # already scopes it and two products must be allowed to share a table name.
    pg_cfg = merge_destination_config("relational_pgvector", {}, settings)
    pg_namespaced = apply_store_namespace("relational_pgvector", pg_cfg, "alpha", "1f2a3dcf", settings)
    assert pg_namespaced["schema_name"] == "kp_alpha_1f2a3dcf"
    assert pg_namespaced["table_name"] == "chunks"

    # A namespaced value already in the config survives a re-save.
    resaved = apply_store_namespace("vector_qdrant", renamed, "alpha", "1f2a3dcf", settings)
    assert resaved["collection_name"] == "kp_alpha_1f2a3dcf"


def test_merge_destination_config_fills_defaults() -> None:
    settings = Settings()
    merged = merge_destination_config(
        "vector_qdrant",
        {"hnsw_m": 24},
        settings,
    )
    assert merged["hnsw_m"] == 24
    assert merged["hnsw_ef_construct"] == 100


def test_normalize_destination_payload_merges_configs() -> None:
    settings = Settings()
    normalized = normalize_destination_payload(
        [
            {
                "destination_type": "cache_redisvl",
                "enabled": True,
                "config": {"ttl_seconds": 600},
            }
        ],
        settings,
    )
    assert normalized[0]["config"]["ttl_seconds"] == 600
    # A profile holds no store name; the product copy assigns it.
    assert "index_prefix" not in normalized[0]["config"]
