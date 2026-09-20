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
    assert qdrant["default_config"]["embedding_model"] == settings.embedding_model
    assert any(field["key"] == "embedding_model" for field in qdrant["fields"])
    for item in destinations:
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


def test_apply_store_namespace_replaces_only_static_defaults() -> None:
    settings = Settings()

    # A config still carrying the shared default is renamed.
    default_cfg = merge_destination_config("vector_qdrant", {}, settings)
    assert default_cfg["collection_name"] == "knowledge_qdrant_collection"
    renamed = apply_store_namespace("vector_qdrant", default_cfg, "alpha", "1f2a3dcf", settings)
    assert renamed["collection_name"] == "kp_alpha_1f2a3dcf"

    # A value the user typed is kept.
    custom_cfg = merge_destination_config(
        "vector_qdrant", {"collection_name": "my_custom_coll"}, settings
    )
    kept = apply_store_namespace("vector_qdrant", custom_cfg, "alpha", "1f2a3dcf", settings)
    assert kept["collection_name"] == "my_custom_coll"

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
        {"collection_name": "custom_collection"},
        settings,
    )
    assert merged["collection_name"] == "custom_collection"
    assert merged["embedding_model"] == settings.embedding_model
    assert merged["litellm_base_url"] == settings.litellm_base_url


def test_normalize_destination_payload_merges_configs() -> None:
    settings = Settings()
    normalized = normalize_destination_payload(
        [
            {
                "destination_type": "cache_redisvl",
                "enabled": True,
                "config": {"index_prefix": "profile_cache"},
            }
        ],
        settings,
    )
    assert normalized[0]["config"]["index_prefix"] == "profile_cache"
    assert normalized[0]["config"]["redis_url"] == settings.redis_url
