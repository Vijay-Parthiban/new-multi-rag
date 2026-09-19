from apps.api.routes.knowledge_destination_schemas import (
    build_destination_types,
    merge_destination_config,
    normalize_destination_payload,
)
from src.shared.config.settings import Settings


def test_build_destination_types_includes_field_schemas() -> None:
    settings = Settings()
    destinations = build_destination_types(settings)
    assert len(destinations) == 5
    qdrant = next(item for item in destinations if item["id"] == "vector_qdrant")
    assert qdrant["default_config"]["embedding_model"] == settings.embedding_model
    assert any(field["key"] == "embedding_model" for field in qdrant["fields"])


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
