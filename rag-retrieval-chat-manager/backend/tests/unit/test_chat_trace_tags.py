"""What a turn writes to a trace, in the form each backend reads.

The two backends disagree on how tags are encoded, and a wrong encoding is invisible: the span
exports, and the tag is quietly dropped. These tests pin the encoding, the derivation of the
tag from the memory gate, and the session trace's shape.
"""

from __future__ import annotations

import json
import uuid
from collections import namedtuple
from datetime import datetime

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_api.session_close import qa_pairs
from rag_api.trace_context import flatten
from rag_shared import tracing

PIPELINE = {
    "id": "dd1cc6c3-d248-42bf-9a70-4ea5ac104f07",
    "name": "TCS Policy Assistant",
    "slug": "tcs-chat",
    "description": "Answers questions about the policies.",
    "rag_strategy": "hybrid",
    "chat_model": "groq-vision",
    "modality_mode": "text",
    "prompt_template_id": None,
    "guardrails_config_id": None,
    "model_settings": {"temperature": 0.1},
}
PRODUCT = {
    "id": "ef2631c1-09fd-4df6-add3-8c2769595b42",
    "name": "tcs store",
    "status": "idle",
    "chunk_strategy": "context_aware",
    "modality_mode": "text",
    "text_embedding_model": "nvidia-embed-textonly",
    "sparse_embedding_model": "Qdrant/bm25",
    "destinations": [
        {"destination_type": "vector_qdrant", "enabled": True, "config": {"collection_name": "kp_x"}},
        {"destination_type": "cache_redisvl", "enabled": True, "config": {"index_prefix": "kp:x"}},
        {"destination_type": "lexical_opensearch", "enabled": False, "config": {}},
    ],
}


@pytest.fixture
def recorder(monkeypatch):
    """Record spans in memory, so the attributes can be read back after the span closes."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    # rag_pipeline_span resolves the tracer through this name, so a patch here captures
    # every span the module creates.
    monkeypatch.setattr(tracing, "get_tracer", lambda: tracer)
    monkeypatch.setattr(tracing, "force_flush", lambda *args, **kwargs: True)
    return exporter


def only_span(recorder):
    spans = recorder.get_finished_spans()
    assert len(spans) == 1, f"expected one span, got {[s.name for s in spans]}"
    return spans[0]


def test_tags_are_written_in_both_encodings(recorder):
    """Langfuse wants a native array. Arize and Phoenix want a JSON string."""
    with tracing.rag_pipeline_span("rag.chat", session_id=str(uuid.uuid4()), tags=["test-session"]):
        pass

    attributes = only_span(recorder).attributes
    assert attributes[tracing.LANGFUSE_TAGS_ATTR] == ("test-session",)
    assert json.loads(attributes[tracing.OPENINFERENCE_TAGS_ATTR]) == ["test-session"]


def test_a_long_tag_is_trimmed_not_dropped(recorder):
    """Langfuse drops a tag past 200 characters, so the limit is applied here instead."""
    with tracing.rag_pipeline_span("rag.chat", tags=["x" * 500]):
        pass

    attributes = only_span(recorder).attributes
    assert len(attributes[tracing.LANGFUSE_TAGS_ATTR][0]) == 200


def test_no_tags_writes_neither_attribute(recorder):
    """A production turn carries no tag, and must not carry an empty one either."""
    with tracing.rag_pipeline_span("rag.chat", tags=[]):
        pass

    attributes = only_span(recorder).attributes
    assert tracing.LANGFUSE_TAGS_ATTR not in attributes
    assert tracing.OPENINFERENCE_TAGS_ATTR not in attributes


def test_attributes_are_written_onto_the_span(recorder):
    with tracing.rag_pipeline_span("rag.chat", attributes={"rag.pipeline.name": "P"}):
        pass

    assert only_span(recorder).attributes["rag.pipeline.name"] == "P"


@pytest.mark.parametrize(
    "trace_mode,has_memory,expected",
    [
        ("test", True, ["test-session"]),
        ("test", False, ["test-stateless"]),
        # A call to the pipeline endpoint is production, and it is labelled the same way.
        ("prod", True, ["prod-session"]),
        ("prod", False, ["prod-stateless"]),
    ],
)
def test_the_tag_follows_the_mode_and_the_memory_gate(trace_mode, has_memory, expected):
    assert tracing.turn_tags(trace_mode, has_memory) == expected


def test_flatten_carries_both_records():
    attributes = flatten(PIPELINE, PRODUCT)

    # Scalars for a reader that does not parse JSON.
    assert attributes["rag.pipeline.name"] == "TCS Policy Assistant"
    assert attributes["rag.pipeline.slug"] == "tcs-chat"
    assert attributes["rag.pipeline.strategy"] == "hybrid"
    assert attributes["rag.knowledge_product.name"] == "tcs store"
    assert attributes["rag.knowledge_product.chunk_strategy"] == "context_aware"
    # Only the enabled stores, so the list describes what retrieval could read.
    assert attributes["rag.knowledge_product.destinations"] == "vector_qdrant,cache_redisvl"

    # The complete records, so nothing about the configuration is lost.
    assert json.loads(attributes["rag.pipeline"])["model_settings"]["temperature"] == 0.1
    assert json.loads(attributes["rag.knowledge_product"])["destinations"][0]["config"]["collection_name"] == "kp_x"

    # Arize reads user-defined values from a single metadata attribute.
    metadata = json.loads(attributes["metadata"])
    assert metadata["pipeline"]["name"] == "TCS Policy Assistant"
    assert metadata["knowledge_product"]["enabled_destinations"] == [
        "vector_qdrant",
        "cache_redisvl",
    ]


def test_flatten_makes_the_fields_langfuse_can_filter_on_filterable():
    """An unrecognised attribute lands in a catch-all Langfuse cannot query, so the fields
    worth filtering on are repeated under the prefix it indexes."""
    attributes = flatten(PIPELINE, PRODUCT)

    assert attributes["langfuse.trace.metadata.pipeline_name"] == "TCS Policy Assistant"
    assert attributes["langfuse.trace.metadata.knowledge_product_name"] == "tcs store"
    assert attributes["langfuse.trace.metadata.chunk_strategy"] == "context_aware"
    assert attributes["langfuse.trace.metadata.enabled_destinations"] == "vector_qdrant, cache_redisvl"

    # Langfuse metadata values are strings, so a non-string would be dropped.
    for key, value in attributes.items():
        if key.startswith("langfuse.trace.metadata."):
            assert isinstance(value, str), f"{key} must be a string for Langfuse"


def test_flatten_survives_a_pipeline_with_no_product():
    attributes = flatten({"id": "p", "name": "Legacy", "rag_strategy": "multimodal"}, None)

    assert attributes["rag.pipeline.name"] == "Legacy"
    assert "rag.knowledge_product.name" not in attributes
    # A destination list that does not exist must not become the string "None".
    assert attributes.get("rag.knowledge_product.destinations") in (None, "")


def test_session_trace_holds_every_turn_in_one_trace(recorder):
    session_id = str(uuid.uuid4())
    trace_id, count = tracing.emit_session_trace(
        session_id=session_id,
        turns=[("q1", "a1"), ("q2", "a2")],
        trace_mode="test",
        tags=["test-session"],
        attributes={"rag.pipeline.name": "TCS Policy Assistant"},
    )

    spans = recorder.get_finished_spans()
    assert count == 2
    # One conversation, and one span per question and answer.
    assert {span.name for span in spans} == {"rag.session", "rag.chat.turn"}
    roots = [span for span in spans if span.name == "rag.session"]
    turns = [span for span in spans if span.name == "rag.chat.turn"]
    assert len(roots) == 1 and len(turns) == 2

    root = roots[0]
    # The whole conversation is one trace, and the caller learns its id.
    assert len({span.context.trace_id for span in spans}) == 1
    assert trace_id == format(root.context.trace_id, "032x")
    # The session id groups it with the per-turn traces of the same conversation.
    assert root.attributes["session.id"] == session_id
    assert root.attributes[tracing.LANGFUSE_TAGS_ATTR] == ("test-session",)
    assert root.attributes["rag.session.turns"] == 2
    assert root.attributes["rag.pipeline.name"] == "TCS Policy Assistant"

    # Each turn hangs off the conversation and carries its own pair.
    for turn in turns:
        assert turn.parent is not None
        assert turn.parent.span_id == root.context.span_id
        # Repeated on every span, because Langfuse only filters on what it finds on the span
        # in front of it.
        assert turn.attributes["session.id"] == session_id
        assert turn.attributes[tracing.LANGFUSE_TAGS_ATTR] == ("test-session",)
        assert json.loads(turn.attributes[tracing.OPENINFERENCE_TAGS_ATTR]) == ["test-session"]
    transcript = json.loads(root.attributes["rag.session.transcript"])
    assert transcript == [
        {"question": "q1", "answer": "a1"},
        {"question": "q2", "answer": "a2"},
    ]
    assert turns[1].attributes["rag.turn.index"] == 2
    assert turns[1].attributes["input.value"] == "q2"
    assert turns[1].attributes["output.value"] == "a2"


def test_session_trace_with_no_turns_still_exports(recorder):
    trace_id, count = tracing.emit_session_trace(
        session_id=str(uuid.uuid4()), turns=[], trace_mode="test", tags=["test-session"]
    )

    assert count == 0
    spans = recorder.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["rag.session.turns"] == 0
    assert trace_id is not None


Message = namedtuple("Message", "role content created_at")


def row(role: str, content: str, created: datetime):
    """One message row, shaped as the repository returns it."""
    return (Message(role, content, created), None, None)


T1 = datetime(2026, 9, 22, 10, 0, 0)
T2 = datetime(2026, 9, 22, 10, 0, 5)


def test_qa_pairs_drops_a_question_with_no_reply():
    rows = [
        row("user", "q1", T1),
        row("assistant", "a1", T1),
        row("user", "q2", T2),
    ]
    assert qa_pairs(rows) == [("q1", "a1")]


def test_qa_pairs_pairs_every_turn_in_order():
    rows = [
        row("user", "q1", T1),
        row("assistant", "a1", T1),
        row("user", "q2", T2),
        row("assistant", "a2", T2),
    ]
    assert qa_pairs(rows) == [("q1", "a1"), ("q2", "a2")]


def test_qa_pairs_survives_a_reply_stored_before_its_question():
    """The two rows of one turn are written in the same transaction, so they share a
    timestamp and the time ordering alone is a coin toss. If the reply comes back first, a
    pairing that trusts the order loses the whole turn."""
    rows = [
        row("assistant", "a1", T1),
        row("user", "q1", T1),
        row("assistant", "a2", T2),
        row("user", "q2", T2),
    ]
    assert qa_pairs(rows) == [("q1", "a1"), ("q2", "a2")]
