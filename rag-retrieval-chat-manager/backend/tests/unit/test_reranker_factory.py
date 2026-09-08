import pytest
from reranker_core.litellm_reranker import LiteLLMReranker, build_reranker
from reranker_core.noop import NoopReranker


def test_build_reranker_selects_backend():
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"
    settings.reranker_model = "nvidia-rerank"

    noop = build_reranker(settings, enabled=False)
    assert isinstance(noop, NoopReranker)

    litellm = build_reranker(settings, enabled=True)
    assert isinstance(litellm, LiteLLMReranker)
    assert litellm.model_name == "nvidia-rerank"
    assert litellm._vl is True

    custom = build_reranker(settings, enabled=True, model="bge-reranker-v2-m3")
    assert isinstance(custom, LiteLLMReranker)
    assert custom.model_name == "bge-reranker-v2-m3"
    assert custom._vl is False
