"""The model list comes from the mode the proxy reports, not from the model name.

The endpoint read `/v1/models` and classified by substring. That called
`All-MiniLM-L6-v2` and `nvidia-rerank` chat, because neither name carries a token the
filter looked for, so both appeared in chat model dropdowns and a user could pick a
model that cannot answer. `/v1/model/info` states the mode, so this file pins that the
endpoint obeys it.

The payloads below are real `/v1/model/info` entries, trimmed to the fields the
endpoint reads.
"""

import asyncio

from apps.api.routes import knowledge_products
from apps.api.routes.knowledge_products import _models_from_model_info


def _entry(name: str, mode: str) -> dict:
    return {"model_name": name, "litellm_params": {}, "model_info": {"mode": mode}}


def test_every_mode_maps_to_its_own_kind():
    payload = {
        "data": [
            _entry("nvidia-embed-textonly", "embedding"),
            _entry("All-MiniLM-L6-v2", "embedding"),
            _entry("nvidia-rerank", "rerank"),
            _entry("Gpt-oss-20b", "chat"),
            _entry("groq-vision", "vision"),
        ]
    }

    by_id = {m["id"]: m["kind"] for m in _models_from_model_info(payload)}

    assert by_id["nvidia-embed-textonly"] == "embedding"
    assert by_id["All-MiniLM-L6-v2"] == "embedding"
    assert by_id["nvidia-rerank"] == "rerank"
    assert by_id["Gpt-oss-20b"] == "chat"
    assert by_id["groq-vision"] == "vision"


def test_an_embedding_model_is_not_reported_as_chat():
    """The exact defect: a name-based guess put this model in the chat list."""
    payload = {"data": [_entry("All-MiniLM-L6-v2", "embedding")]}

    kinds = [m["kind"] for m in _models_from_model_info(payload)]

    assert kinds == ["embedding"]


def test_completion_is_treated_as_chat():
    """LiteLLM reports `completion` for some text models. Callers ask for chat."""
    payload = {"data": [_entry("legacy-text", "completion")]}

    assert _models_from_model_info(payload) == [{"id": "legacy-text", "kind": "chat"}]


def test_a_model_with_no_mode_is_left_out():
    payload = {"data": [{"model_name": "mystery"}, {"model_name": "blank", "model_info": {}}]}

    assert _models_from_model_info(payload) == []


def test_an_unknown_mode_is_left_out():
    payload = {"data": [_entry("audio-only", "audio_speech")]}

    assert _models_from_model_info(payload) == []


def test_a_bare_string_entry_is_left_out():
    """`/v1/models` returns bare ids. This endpoint needs the mode, so it skips them."""
    payload = {"data": ["bare-id", _entry("Gpt-oss-20b", "chat")]}

    assert _models_from_model_info(payload) == [{"id": "Gpt-oss-20b", "kind": "chat"}]


def test_the_endpoint_filters_by_the_reported_kind(monkeypatch):
    async def fake() -> list[dict[str, str]]:
        return [
            {"id": "nvidia-embed-textonly", "kind": "embedding"},
            {"id": "nvidia-rerank", "kind": "rerank"},
            {"id": "Gpt-oss-20b", "kind": "chat"},
            {"id": "groq-vision", "kind": "vision"},
        ]

    monkeypatch.setattr(knowledge_products, "_proxy_models", fake)

    for kind in ("embedding", "rerank", "chat", "vision"):
        result = asyncio.run(knowledge_products.list_litellm_models(kind))
        assert [m["kind"] for m in result["models"]] == [kind], kind
        assert result["source"] == "litellm"


def test_a_kind_with_no_match_returns_nothing_not_everything(monkeypatch):
    """The old fallback listed every model when the filter matched none."""

    async def fake() -> list[dict[str, str]]:
        return [{"id": "Gpt-oss-20b", "kind": "chat"}]

    monkeypatch.setattr(knowledge_products, "_proxy_models", fake)

    result = asyncio.run(knowledge_products.list_litellm_models("rerank"))

    assert result["models"] == []


def test_the_sparse_model_is_always_listed(monkeypatch):
    """It is a fastembed model, so it is never in the proxy's own list."""

    async def fake() -> list[dict[str, str]]:
        return [{"id": "Gpt-oss-20b", "kind": "chat"}]

    monkeypatch.setattr(knowledge_products, "_proxy_models", fake)

    all_models = asyncio.run(knowledge_products.list_litellm_models("all"))
    sparse = asyncio.run(knowledge_products.list_litellm_models("sparse"))

    assert any(m["kind"] == "sparse" for m in all_models["models"])
    assert sparse["models"] and all(m["kind"] == "sparse" for m in sparse["models"])


def test_a_failed_proxy_call_says_so(monkeypatch):
    async def boom() -> list[dict[str, str]]:
        raise OSError("connection refused")

    monkeypatch.setattr(knowledge_products, "_proxy_models", boom)

    result = asyncio.run(knowledge_products.list_litellm_models("chat"))

    assert result["source"] == "fallback"
    assert result["warning"]
    assert all(m["kind"] == "chat" for m in result["models"])
