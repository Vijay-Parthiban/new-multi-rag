"""Model settings: where a sampling value comes from, and that it reaches the call.

The chain is request override -> pipeline settings -> service Settings. The
distinction that matters is None versus a real value: None means "not set, keep
falling back", while 0 is a value the caller chose and must survive. Getting that
wrong silently ignores a deliberate temperature of 0.

The last group asserts against a fake client, so it checks the arguments the
model call actually receives rather than what the code intends to pass. No
network and no model call.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag_core.schemas import ModelSettings, PipelineConfig, PipelineRequest
from rag_shared.config import Settings
from rag_shared.types import RerankedChunk

from generation_core.generator import Generator


def _chunk(content: str = "text") -> RerankedChunk:
    """A text chunk. generate_stream returns early on an empty list, so a
    streaming test needs at least one."""
    return RerankedChunk(
        id="1",
        content=content,
        source_type="web_scrape",
        source_id="job-1",
        source_locator="https://example.com/page",
        chunk_index=0,
        chunk_type="text",
        retrieval_score=0.9,
        rerank_score=0.95,
    )


@pytest.fixture()
def generator(monkeypatch):
    """A Generator whose client records the arguments of the next call."""
    gen = Generator(Settings())
    recorded: dict = {}

    class _Completions:
        def create(self, **kwargs):
            recorded.clear()
            recorded.update(kwargs)

            class _Message:
                content = "ok"

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]

            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    gen._client = _Client()
    return gen, recorded


def test_no_settings_keeps_the_service_defaults(generator):
    gen, recorded = generator
    settings = Settings()

    gen._generate_text("q", [])

    assert recorded["max_tokens"] == settings.chat_max_tokens
    assert recorded["temperature"] == settings.chat_temperature


def test_unset_fields_are_not_sent_at_all(generator):
    """top_p and top_k are omitted, not sent as null or as a default."""
    gen, recorded = generator

    gen._generate_text("q", [])

    assert "top_p" not in recorded
    assert "top_k" not in recorded


def test_pipeline_settings_reach_the_model_call(generator):
    gen, recorded = generator
    cfg = PipelineConfig(
        model_settings=ModelSettings(temperature=0.1, top_p=0.9, top_k=40, max_tokens=7)
    )

    gen._generate_text("q", [], **cfg.sampling_kwargs())

    assert recorded["temperature"] == 0.1
    assert recorded["top_p"] == 0.9
    assert recorded["top_k"] == 40
    assert recorded["max_tokens"] == 7


def test_streaming_receives_the_same_settings(generator):
    """The streaming path must not quietly drop what the blocking path honours."""
    gen, recorded = generator

    def _stream(**kwargs):
        recorded.clear()
        recorded.update(kwargs)
        return iter([])

    gen._client.chat.completions.create = _stream
    cfg = PipelineConfig(model_settings=ModelSettings(temperature=0.1, top_p=0.9))

    list(gen.generate_stream("q", [_chunk()], **cfg.sampling_kwargs()))

    assert recorded["temperature"] == 0.1
    assert recorded["top_p"] == 0.9


def test_temperature_zero_is_a_value_not_an_absence(generator):
    """0.0 is falsy, and a truthiness check would discard it."""
    gen, recorded = generator

    gen._generate_text("q", [], **PipelineConfig(model_settings=ModelSettings(temperature=0.0)).sampling_kwargs())

    assert recorded["temperature"] == 0.0


def test_top_k_zero_means_off(generator):
    gen, recorded = generator

    gen._generate_text("q", [], **PipelineConfig(model_settings=ModelSettings(top_k=0)).sampling_kwargs())

    assert "top_k" not in recorded


def test_a_partial_override_falls_back_field_by_field(generator):
    gen, recorded = generator
    settings = Settings()

    gen._generate_text(
        "q", [], **PipelineConfig(model_settings=ModelSettings(temperature=0.4)).sampling_kwargs()
    )

    assert recorded["temperature"] == 0.4
    assert recorded["max_tokens"] == settings.chat_max_tokens


def test_a_request_override_survives_to_config():
    request = PipelineRequest(query="q", model_settings=ModelSettings(temperature=0.35, top_p=0.8))
    config = request.to_config()

    assert config.model_settings is not None
    assert config.sampling_kwargs()["temperature"] == 0.35
    assert config.sampling_kwargs()["top_p"] == 0.8


def test_a_request_without_settings_leaves_the_config_unset():
    config = PipelineRequest(query="q").to_config()

    assert config.model_settings is None
    assert config.sampling_kwargs() == {
        "max_tokens": None,
        "temperature": None,
        "top_p": None,
        "top_k": None,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": 3.0},
        {"temperature": -0.1},
        {"top_p": 0.0},
        {"top_p": 1.5},
        {"top_k": -1},
        {"max_tokens": 0},
    ],
)
def test_out_of_range_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        ModelSettings(**bad)


def test_a_pipeline_with_malformed_settings_does_not_break_a_turn():
    """Saved JSON is not trusted: it is dropped, and the defaults take over."""
    from rag_api.routes.assistants import _pipeline_model_settings

    assert _pipeline_model_settings({}) is None
    assert _pipeline_model_settings({"model_settings": None}) is None
    assert _pipeline_model_settings({"model_settings": {"temperature": 0.3}}).temperature == 0.3
    # Out of range, so unusable: the turn must still run.
    assert _pipeline_model_settings({"model_settings": {"temperature": 99.0}}) is None
    assert _pipeline_model_settings({"model_settings": "not a mapping"}) is None
