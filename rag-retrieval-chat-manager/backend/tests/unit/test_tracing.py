"""Trace mode tagging and session trace grouping.

These run against an in-memory span exporter, so they assert what actually reaches the
collector rather than what the code intends to send. No network and no model call.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import rag_shared.tracing as tracing


@pytest.fixture()
def spans(monkeypatch):
    """Point the module tracer at an exporter that keeps the spans in memory."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_tracer", provider.get_tracer("test"))
    monkeypatch.setattr(tracing, "_provider", provider)
    monkeypatch.setattr(tracing, "_initialized", True)
    yield exporter
    exporter.clear()


def _turn(session_id: str | None = None, *, query: str = "a question", mode: str = "prod", session_trace: bool = False):
    with tracing.rag_pipeline_span(
        "rag.chat",
        session_id=session_id,
        query=query,
        trace_mode=mode,
        session_trace=session_trace,
    ):
        pass


# ── the mode tag ──────────────────────────────────────────────────────────────


def test_normalize_trace_mode() -> None:
    assert tracing.normalize_trace_mode("test") == "test"
    assert tracing.normalize_trace_mode("TEST") == "test"
    assert tracing.normalize_trace_mode("  Test  ") == "test"
    # Everything else is production: a missing header must never read as a test turn.
    assert tracing.normalize_trace_mode(None) == "prod"
    assert tracing.normalize_trace_mode("") == "prod"
    assert tracing.normalize_trace_mode("prod") == "prod"
    assert tracing.normalize_trace_mode("staging") == "prod"


def test_a_test_turn_is_tagged_test(spans: InMemorySpanExporter) -> None:
    _turn(mode="test")
    span = spans.get_finished_spans()[0]
    assert span.attributes["deployment.environment"] == "test"
    assert span.attributes["rag.trace_mode"] == "test"


def test_the_default_is_production(spans: InMemorySpanExporter) -> None:
    with tracing.rag_pipeline_span("rag.chat", query="q"):
        pass
    span = spans.get_finished_spans()[0]
    assert span.attributes["rag.trace_mode"] == "prod"
    assert span.attributes["deployment.environment"] == "prod"


def test_a_prod_turn_is_tagged_prod(spans: InMemorySpanExporter) -> None:
    _turn(mode="prod")
    span = spans.get_finished_spans()[0]
    assert span.attributes["deployment.environment"] == "prod"
    assert span.attributes["rag.trace_mode"] == "prod"


def test_the_turn_carries_the_query_and_session(spans: InMemorySpanExporter) -> None:
    session_id = str(uuid.uuid4())
    _turn(session_id, query="what is this")
    span = spans.get_finished_spans()[0]
    assert span.attributes["input.value"] == "what is this"
    assert span.attributes["session.id"] == session_id
    assert span.attributes["langfuse.session.id"] == session_id


# ── the session trace ─────────────────────────────────────────────────────────


def test_session_turns_share_one_trace(spans: InMemorySpanExporter) -> None:
    session_id = str(uuid.uuid4())
    _turn(session_id, query="first", session_trace=True)
    _turn(session_id, query="second", session_trace=True)

    finished = spans.get_finished_spans()
    assert len(finished) == 2
    # One trace for the whole session, and it is the deterministic id.
    assert finished[0].context.trace_id == finished[1].context.trace_id
    assert finished[0].context.trace_id == tracing.session_trace_ids(session_id)[0]
    # Separate observations inside that trace, so each Q/A stays readable.
    assert finished[0].context.span_id != finished[1].context.span_id


def test_the_session_trace_id_is_stable_across_processes(spans: InMemorySpanExporter) -> None:
    """The id cannot depend on anything in memory, because the turns arrive as separate requests."""
    session_id = str(uuid.uuid4())
    _turn(session_id, query="first", session_trace=True)
    first_trace = spans.get_finished_spans()[0].context.trace_id
    # A different process would compute the same value from the session id alone.
    assert first_trace == tracing.session_trace_ids(session_id)[0]


def test_without_a_session_each_turn_is_its_own_trace(spans: InMemorySpanExporter) -> None:
    session_id = str(uuid.uuid4())
    _turn(session_id, query="first", session_trace=False)
    _turn(session_id, query="second", session_trace=False)

    finished = spans.get_finished_spans()
    assert len(finished) == 2
    assert finished[0].context.trace_id != finished[1].context.trace_id


def test_two_sessions_do_not_share_a_trace(spans: InMemorySpanExporter) -> None:
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    _turn(one, session_trace=True)
    _turn(two, session_trace=True)
    finished = spans.get_finished_spans()
    assert finished[0].context.trace_id != finished[1].context.trace_id


def test_a_non_uuid_session_falls_back_to_one_trace_per_turn(spans: InMemorySpanExporter) -> None:
    """A session id that cannot be a UUID cannot produce a stable trace id, so it gets none."""
    for query in ("first", "second"):
        with tracing.rag_pipeline_span(
            "rag.chat", session_id="not-a-uuid", query=query, session_trace=True
        ):
            pass

    finished = spans.get_finished_spans()
    assert len(finished) == 2
    # No shared trace, because there is no derivable id to share.
    assert finished[0].context.trace_id != finished[1].context.trace_id
    # And the marker is absent, so the turn does not claim a session trace it never joined.
    assert "rag.session_trace" not in finished[0].attributes


def test_the_session_turn_is_marked(spans: InMemorySpanExporter) -> None:
    _turn(str(uuid.uuid4()), session_trace=True)
    assert spans.get_finished_spans()[0].attributes["rag.session_trace"] is True


# ── the metrics span ──────────────────────────────────────────────────────────


def test_session_trace_ids_rejects_non_uuids() -> None:
    assert tracing.session_trace_ids(None) is None
    assert tracing.session_trace_ids("") is None
    assert tracing.session_trace_ids("not-a-uuid") is None
    assert tracing.session_trace_ids("7b1f0d2a-6c8e-4a1b-9f3d-2e5a7c9b1d40") is not None


def test_current_span_ids_is_hex_inside_a_span(spans: InMemorySpanExporter) -> None:
    with tracing.rag_pipeline_span("rag.chat", query="q") as span:
        ids = tracing.current_span_ids()
        ctx = span.get_span_context()
    assert ids is not None
    assert ids == (format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))
    assert len(ids[0]) == 32 and len(ids[1]) == 16


def test_current_span_ids_is_none_outside_a_span() -> None:
    assert tracing.current_span_ids() is None


def test_the_metrics_span_joins_the_turn_trace(spans: InMemorySpanExporter) -> None:
    """Without this the same question appears twice in Langfuse and Phoenix."""
    session_id = str(uuid.uuid4())
    with tracing.rag_pipeline_span("rag.chat", session_id=session_id, query="q", session_trace=True) as span:
        ctx = span.get_span_context()
        parent = (format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))

    tracing.emit_rag_pipeline_trace(
        session_id=session_id,
        message_id="m-1",
        query="q",
        answer="a",
        scores={"faithfulness": 0.9},
        trace_mode="test",
        parent=parent,
        flush=False,
    )

    finished = spans.get_finished_spans()
    assert len(finished) == 2
    traces = {s.context.trace_id for s in finished}
    assert len(traces) == 1, "the metrics span opened its own trace"
    metrics = [s for s in finished if s.name == "rag.pipeline.metrics"][0]
    assert metrics.parent is not None
    assert metrics.parent.span_id == ctx.span_id
    assert metrics.attributes["eval.faithfulness"] == 0.9
    assert metrics.attributes["rag.trace_mode"] == "test"


def test_the_metrics_span_without_a_parent_opens_its_own_trace(spans: InMemorySpanExporter) -> None:
    """The documented fallback for a turn traced before migration 004."""
    tracing.emit_rag_pipeline_trace(
        session_id=str(uuid.uuid4()),
        message_id="m-2",
        query="q",
        answer="a",
        flush=False,
    )
    finished = spans.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].parent is None
