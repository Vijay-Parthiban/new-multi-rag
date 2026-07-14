from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rag_shared.chunk_utils import is_image_chunk, split_chunks
from rag_shared.types import RerankedChunk, RetrievedChunk


def _chunk(content: str, *, chunk_type: str = "text") -> RetrievedChunk:
    return RetrievedChunk(
        id="1",
        content=content,
        source_type="web_scrape",
        source_id="job",
        source_locator="https://example.com",
        chunk_index=0,
        chunk_type=chunk_type,
        retrieval_score=1.0,
    )


def test_is_image_chunk_from_type():
    chunk = _chunk("data:image/png;base64,abc", chunk_type="image")
    assert is_image_chunk(chunk) is True


def test_is_image_chunk_from_data_uri():
    chunk = _chunk("data:image/png;base64,abc", chunk_type="text")
    assert is_image_chunk(chunk) is True


def test_split_chunks():
    text = _chunk("hello", chunk_type="text")
    image = _chunk("data:image/png;base64,abc", chunk_type="image")
    text_only, image_only = split_chunks([text, image, text])
    assert len(text_only) == 2
    assert len(image_only) == 1


@patch("reranker_core.litellm_reranker.OpenAI")
def test_nvidia_reranker_vl_documents_and_rankings(mock_openai_cls):
    from reranker_core.litellm_reranker import LiteLLMReranker

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.post.return_value = {
        "rankings": [{"index": 0, "logit": 0.2}, {"index": 1, "logit": 0.9}],
    }

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"

    chunks = [
        _chunk("text chunk", chunk_type="text"),
        _chunk("data:image/png;base64,abc", chunk_type="image"),
    ]
    reranker = LiteLLMReranker(settings, model_name="nvidia-rerank")
    result = reranker.rerank("query", chunks, top_k=2)

    payload = mock_client.post.call_args.kwargs["body"]
    assert payload["model"] == "nvidia-rerank"
    assert "top_n" not in payload
    assert payload["documents"][0] == {"text": "text chunk"}
    assert payload["documents"][1]["text"] == "https://example.com"
    assert payload["documents"][1]["image"] == "data:image/png;base64,abc"
    assert result[0].rerank_score == 0.9


@patch("reranker_core.litellm_reranker.OpenAI")
def test_litellm_reranker_parse_scores(mock_openai_cls):
    from reranker_core.litellm_reranker import LiteLLMReranker

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.post.return_value = {
        "results": [{"index": 0, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.9}],
    }

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"

    chunks = [
        _chunk("text chunk", chunk_type="text"),
        _chunk("another chunk", chunk_type="text"),
    ]
    reranker = LiteLLMReranker(settings, model_name="bge-reranker-v2-m3")
    result = reranker.rerank("query", chunks, top_k=2)

    payload = mock_client.post.call_args.kwargs["body"]
    assert payload["model"] == "bge-reranker-v2-m3"
    assert payload["query"] == "query"
    assert payload["documents"] == ["text chunk", "another chunk"]
    assert payload["top_n"] == 2
    assert result[0].id == "1"
    assert result[0].rerank_score == 0.9


@patch("reranker_core.litellm_reranker.OpenAI")
def test_litellm_reranker_uses_caption_for_image_chunks(mock_openai_cls):
    from reranker_core.litellm_reranker import LiteLLMReranker

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.post.return_value = {
        "results": [{"index": 0, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.8}],
    }

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"

    chunks = [
        RetrievedChunk(
            id="t",
            content="text chunk",
            source_type="web_scrape",
            source_id="job",
            source_locator="https://example.com/page",
            chunk_index=0,
            chunk_type="text",
            retrieval_score=1.0,
        ),
        RetrievedChunk(
            id="i",
            content="data:image/png;base64,abc",
            source_type="web_scrape",
            source_id="job",
            source_locator="https://example.com/page",
            chunk_index=0,
            chunk_type="image",
            title="Homepage screenshot",
            retrieval_score=0.9,
        ),
    ]
    reranker = LiteLLMReranker(settings, model_name="bge-reranker-v2-m3")
    reranker.rerank("query", chunks, top_k=2)

    payload = mock_client.post.call_args.kwargs["body"]
    assert payload["documents"][0] == "text chunk"
    assert payload["documents"][1] == "Homepage screenshot"
    assert "base64" not in str(payload["documents"][1])


@patch("generation_core.generator.VisionGenerator.generate", return_value="vision answer")
@patch("generation_core.generator.Generator._generate_text", return_value="text answer")
@patch("generation_core.generator.Generator._fuse_answers", return_value="final answer")
def test_generator_fuses_text_and_vision(mock_fuse, mock_text, mock_vision):
    from generation_core.generator import Generator

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"
    settings.chat_model = "gpt-4o-mini"
    settings.vision_model = "groq-vision"
    settings.chat_max_tokens = 512
    settings.chat_temperature = 0.2

    settings.fusion_model = "gpt-4o-mini"

    generator = Generator(settings)
    chunks = [
        RerankedChunk(
            id="t",
            content="text",
            source_type="web_scrape",
            source_id="job",
            source_locator="https://example.com/page",
            chunk_index=0,
            chunk_type="text",
            retrieval_score=1.0,
            rerank_score=1.0,
        ),
        RerankedChunk(
            id="i",
            content="data:image/png;base64,abc",
            source_type="web_scrape",
            source_id="job",
            source_locator="https://example.com/page",
            chunk_index=0,
            chunk_type="image",
            retrieval_score=1.0,
            rerank_score=0.9,
        ),
    ]

    answer = generator.generate("question", chunks)
    assert answer.answer == "final answer"
    mock_text.assert_called_once()
    mock_vision.assert_called_once()
    mock_fuse.assert_called_once()


@patch("generation_core.generator.VisionGenerator.generate", return_value="vision only")
@patch("generation_core.generator.Generator._generate_text")
def test_generator_vision_only(mock_text, mock_vision):
    from generation_core.generator import Generator

    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"
    settings.chat_model = "gpt-4o-mini"
    settings.vision_model = "groq-vision"
    settings.chat_max_tokens = 512
    settings.chat_temperature = 0.2

    settings.fusion_model = "gpt-4o-mini"

    generator = Generator(settings)
    chunks = [
        RerankedChunk(
            id="i",
            content="data:image/png;base64,abc",
            source_type="web_scrape",
            source_id="job",
            source_locator="https://example.com/page",
            chunk_index=0,
            chunk_type="image",
            retrieval_score=1.0,
            rerank_score=0.9,
        ),
    ]

    answer = generator.generate("question", chunks)
    assert answer.answer == "vision only"
    mock_text.assert_not_called()
