import json
import logging
import os
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import unquote

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    HAVE_OTEL = True
except ImportError:
    HAVE_OTEL = False
    trace = None

try:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HAVE_HTTPX_OTEL = True
except ImportError:
    HAVE_HTTPX_OTEL = False
logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None
_provider: TracerProvider | None = None
_initialized = False


def _parse_resource_attributes(raw: str) -> dict[str, str]:
    """Parse OTEL_RESOURCE_ATTRIBUTES (comma-separated key=value)."""
    out: dict[str, str] = {}
    if not raw or not raw.strip():
        out = {
            "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
            "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "rag-platform"),
        }
    else:
        for pair in raw.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()

    # Arize requires model_id or arize.project.name on the span resource
    arize_model = os.getenv("ARIZE_MODEL_ID", "").strip()
    arize_project = os.getenv("ARIZE_PROJECT_NAME", "").strip()
    service_name = os.getenv("OTEL_SERVICE_NAME", "rag-platform")
    out.setdefault("model_id", arize_model or service_name)
    if arize_project:
        out.setdefault("arize.project.name", arize_project)

    return out


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse comma-separated key=value pairs (first '=' splits key from value)."""
    headers: dict[str, str] = {}
    if not raw or not raw.strip():
        return headers
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = unquote(value.strip())
    return headers


def _traces_endpoint(endpoint: str) -> str:
    """Normalize OTLP base or traces URL to a /v1/traces HTTP endpoint."""
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        return base
    return f"{base}/v1/traces"


# The header the Chat page sets on its own requests. The Chat page and an external caller
# hit the same route, so the header is the only thing that separates a test turn from a
# production one. Anything without it counts as production.
TRACE_MODE_HEADER = "X-RAG-Trace-Mode"
TRACE_MODE_TEST = "test"
TRACE_MODE_PROD = "prod"


def normalize_trace_mode(raw: str | None) -> str:
    """Map a request header value to a trace mode. Anything unrecognised is production."""
    return TRACE_MODE_TEST if (raw or "").strip().lower() == TRACE_MODE_TEST else TRACE_MODE_PROD


# Both backends group a conversation by session id, and both take a list of tags, but they
# disagree on the encoding. Langfuse maps `langfuse.trace.tags` as a native string array.
# Arize and Phoenix follow OpenInference, which stores `tag.tags` as a JSON string. Both are
# written, so one span renders correctly in either platform.
LANGFUSE_TAGS_ATTR = "langfuse.trace.tags"
OPENINFERENCE_TAGS_ATTR = "tag.tags"

# A turn is labelled by its mode and by the one thing that changes its behaviour: whether the
# pipeline keeps the conversation. The tag is derived, never client-supplied, so it always
# agrees with what the turn actually did.
#
# The mode is part of the tag because the two paths are otherwise indistinguishable in a
# backend: a turn from the Chat page and a call to the pipeline endpoint carry the same span
# name and the same attributes. `deployment.environment` separates them too, but a tag can be
# read on the same screen as the trace.
TAG_TEST_SESSION = "test-session"
TAG_TEST_STATELESS = "test-stateless"
TAG_PROD_SESSION = "prod-session"
TAG_PROD_STATELESS = "prod-stateless"


def turn_tags(trace_mode: str, has_session_memory: bool) -> list[str]:
    """The tag for one turn: `{mode}-{session|stateless}`.

    The mode picks the prefix and the memory gate picks the suffix. A turn from the Chat page
    reads `test-session` or `test-stateless`; a call to the pipeline endpoint reads
    `prod-session` or `prod-stateless`.
    """
    if trace_mode == TRACE_MODE_TEST:
        return [TAG_TEST_SESSION if has_session_memory else TAG_TEST_STATELESS]
    return [TAG_PROD_SESSION if has_session_memory else TAG_PROD_STATELESS]


def set_span_tags(span: trace.Span, tags: Sequence[str]) -> None:
    """Tag a span for both backends.

    Langfuse tags are capped at 200 characters and it drops an over-long one, so a tag is
    trimmed here rather than silently lost. `set_span_attr` cannot be used: it stringifies
    anything that is not a scalar, and Langfuse needs a real array.
    """
    cleaned = [tag[:200] for tag in tags if tag]
    if not cleaned:
        return
    span.set_attribute(LANGFUSE_TAGS_ATTR, cleaned)
    span.set_attribute(OPENINFERENCE_TAGS_ATTR, json.dumps(cleaned))


def session_trace_ids(session_id: str | None) -> tuple[int, int] | None:
    """The fixed trace id and root span id of a session, derived from its UUID.

    A session runs across many HTTP requests, so its trace cannot be one open span. Deriving
    the ids from the session id instead means every turn of a session lands in the same trace
    with no shared state anywhere: the same session id always yields the same two numbers,
    in any process.

    Returns None when the id is not a UUID, which is the only case that cannot be derived.
    """
    if not session_id:
        return None
    try:
        raw = uuid.UUID(str(session_id)).bytes
    except (ValueError, AttributeError, TypeError):
        return None
    trace_id = int.from_bytes(raw, "big")
    span_id = int.from_bytes(raw[:8], "big")
    # A trace or span id of zero is invalid in OTLP.
    if trace_id == 0 or span_id == 0:
        return None
    return trace_id, span_id


def current_span_ids() -> tuple[str, str] | None:
    """The hex trace id and span id of the active span.

    Stored on the turn so a later process, the metrics worker, can file its own span into the
    same trace instead of opening a second one for the same question.
    """
    if not HAVE_OTEL:
        return None
    try:
        ctx = trace.get_current_span().get_span_context()
    except Exception:  # noqa: BLE001
        return None
    if ctx is None or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def init_tracing() -> None:
    """Configure the global TracerProvider and OTLP HTTP exporter → collector."""
    global _tracer, _provider, _initialized
    if _initialized:
        return
    if not HAVE_OTEL:
        logger.info("OpenTelemetry not installed, tracing disabled")
        _initialized = True
        return

    enabled = os.getenv("OTEL_TRACING_ENABLED", "true").lower() == "true"
    service_name = os.getenv("OTEL_SERVICE_NAME", "rag-platform")

    if not enabled:
        logger.info("OpenTelemetry tracing is disabled")
        if trace:
            _tracer = trace.get_tracer(service_name)
        _initialized = True
        return

    console_enabled = os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true"

    resource_attrs = _parse_resource_attributes(os.getenv("OTEL_RESOURCE_ATTRIBUTES", ""))
    resource_attrs.setdefault("service.name", service_name)

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)

    # Apps export to the collector; collector fans out to Langfuse / Arize / Grafana
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318").strip()
    traces_url = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    raw_headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()

    if traces_url or endpoint:
        headers = _parse_otlp_headers(raw_headers)
        target = traces_url.rstrip("/") if traces_url else _traces_endpoint(endpoint)
        exporter = OTLPSpanExporter(endpoint=target, headers=headers or None)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("OTel HTTP exporter targeting %s", target)

    if console_enabled:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        logger.info("OTel console exporter enabled")

    trace.set_tracer_provider(provider)
    _provider = provider
    _tracer = trace.get_tracer(service_name)

    # Auto-instrument outbound HTTP (LiteLLM, Qdrant, etc.) as child spans when a parent exists
    if HAVE_HTTPX_OTEL:
        HTTPXClientInstrumentor().instrument()
    _initialized = True
    logger.info("OpenTelemetry tracing initialized service=%s", service_name)


def get_tracer() -> trace.Tracer:
    """Return the process tracer. Calls init_tracing() lazily if needed."""
    global _tracer
    if not _initialized:
        init_tracing()
    if _tracer is None:
        _tracer = trace.get_tracer(os.getenv("OTEL_SERVICE_NAME", "rag-platform"))
    return _tracer


def force_flush(timeout_millis: int = 10_000) -> bool:
    """Flush pending spans to the OTLP exporter (important for RQ workers)."""
    if _provider is None:
        return True
    try:
        return bool(_provider.force_flush(timeout_millis))
    except Exception:
        logger.exception("OTel force_flush failed")
        return False


def set_span_attr(span: trace.Span, key: str, value: Any) -> None:
    """Set a span attribute, skipping None and coercing non-primitive values."""
    if value is None:
        return
    if isinstance(value, (bool, int, float, str)):
        span.set_attribute(key, value)
    else:
        span.set_attribute(key, str(value))


def _apply_turn_attributes(
    span: trace.Span,
    *,
    session_id: str | None,
    message_id: str | None,
    query: str | None,
    answer: str | None,
    observation_type: str,
    model: str | None,
    metadata: dict[str, Any] | None,
    trace_mode: str,
) -> None:
    """Write the attributes both backends read off a turn span."""
    # Langfuse reads langfuse.*; Phoenix reads the OpenInference keys. Both are written so
    # one span renders properly in either platform.
    set_span_attr(span, "langfuse.observation.type", observation_type)
    set_span_attr(span, "openinference.span.kind", "CHAIN")
    set_span_attr(span, "deployment.environment", trace_mode)
    set_span_attr(span, "rag.trace_mode", trace_mode)
    if session_id:
        set_span_attr(span, "langfuse.session.id", session_id)
        set_span_attr(span, "session.id", session_id)
    if message_id:
        set_span_attr(span, "langfuse.observation.metadata.message_id", message_id)
        set_span_attr(span, "rag.message_id", message_id)
    if query is not None:
        set_span_attr(span, "langfuse.trace.input", query)
        set_span_attr(span, "langfuse.observation.input", query)
        set_span_attr(span, "input.value", query)
        set_span_attr(span, "input.mime_type", "text/plain")
    if answer is not None:
        set_span_attr(span, "langfuse.trace.output", answer)
        set_span_attr(span, "langfuse.observation.output", answer)
        set_span_attr(span, "output.value", answer)
        set_span_attr(span, "output.mime_type", "text/plain")
    if model:
        set_span_attr(span, "langfuse.observation.model.name", model)
        set_span_attr(span, "gen_ai.request.model", model)
    if metadata:
        for key, val in metadata.items():
            set_span_attr(span, f"langfuse.observation.metadata.{key}", val)


def _parent_context(trace_id_hex: str, span_id_hex: str):
    """A context whose active span is a reference to an existing span id.

    This is how a span is filed into a trace that was created elsewhere: the session trace
    for a session turn, or the original turn for the metrics span that arrives later. The
    referenced span need not exist in the same payload; both Langfuse and Phoenix group by
    trace id and treat a missing parent as a root.
    """
    parent = trace.NonRecordingSpan(
        trace.SpanContext(
            trace_id=int(trace_id_hex, 16),
            span_id=int(span_id_hex, 16),
            is_remote=True,
            trace_flags=trace.TraceFlags(0x01),
        )
    )
    return trace.set_span_in_context(parent)


@contextmanager
def rag_pipeline_span(
    name: str = "rag.pipeline",
    *,
    session_id: str | None = None,
    message_id: str | None = None,
    query: str | None = None,
    answer: str | None = None,
    observation_type: str = "generation",
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_mode: str = TRACE_MODE_PROD,
    session_trace: bool = False,
    parent: tuple[str, str] | None = None,
    tags: Sequence[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """
    Create a root RAG span with Langfuse- and Phoenix-recognized attributes.

    `trace_mode` tags the span as a test or a production turn, and is the field the Real Time
    Monitoring page filters on.

    `session_trace` files this turn into the trace holding every turn of the session. It needs
    a UUID `session_id`, so only a pipeline with Redis memory can produce one.

    `parent` attaches the span to a trace created elsewhere, given as hex
    `(trace_id, span_id)`. The metrics span uses it to join the turn it belongs to rather
    than opening a second trace for the same question.

    `tags` labels the trace in both backends. `attributes` carries pre-flattened context,
    which is how the pipeline and Knowledge Product records reach the trace.
    """
    tracer = get_tracer()

    context = None
    joined_session = False
    if parent is not None:
        context = _parent_context(*parent)
    elif session_trace:
        ids = session_trace_ids(session_id)
        if ids is not None:
            # Every turn of the session becomes a child of one fixed id derived from the
            # session, so all of them land in one trace.
            #
            # No span is emitted for that id, and that is deliberate: the id is the same in
            # every process, so emitting one would repeat the same span on every turn. Both
            # backends group by trace id and show the turns as roots of the session trace.
            context = _parent_context(format(ids[0], "032x"), format(ids[1], "016x"))
            joined_session = True

    with tracer.start_as_current_span(
        name, context=context, kind=trace.SpanKind.SERVER
    ) as span:
        _apply_turn_attributes(
            span,
            session_id=session_id,
            message_id=message_id,
            query=query,
            answer=answer,
            observation_type=observation_type,
            model=model,
            metadata=metadata,
            trace_mode=trace_mode,
        )
        if joined_session:
            # Marks the turn as belonging to a session trace, so a reader can tell the two
            # traces of a session turn apart without knowing the session id.
            set_span_attr(span, "rag.session_trace", True)
        set_span_tags(span, tags or [])
        for key, value in (attributes or {}).items():
            set_span_attr(span, key, value)
        yield span


def emit_rag_pipeline_trace(
    *,
    session_id: str,
    message_id: str,
    query: str,
    answer: str,
    latency_ms: dict | None = None,
    scores: dict | None = None,
    retrieved_chunks: list | None = None,
    trace_info: dict | None = None,
    flush: bool = True,
    trace_mode: str = TRACE_MODE_PROD,
    parent: tuple[str, str] | None = None,
) -> None:
    """
    Emit the metrics span for a turn (used by eval-worker after the metrics compute).

    Pass `parent` as the hex `(trace_id, span_id)` of the original turn and the metrics land
    inside that turn's trace. Leave it out and this opens a trace of its own, which shows the
    same question twice in both backends.

    Spans are batched via BatchSpanProcessor; set flush=True (default) so RQ jobs
    push to the collector before the worker moves on.
    """
    trace_info = trace_info or {}
    latency_ms = latency_ms or {}
    scores = scores or {}
    chunks = retrieved_chunks or []

    metadata = {
        "retrieval_mode": trace_info.get("retrieval_mode"),
        "rerank_enabled": trace_info.get("rerank_enabled"),
    }

    with rag_pipeline_span(
        "rag.pipeline.metrics",
        session_id=session_id,
        message_id=message_id,
        query=query,
        answer=answer,
        observation_type="generation",
        model=trace_info.get("generation_model"),
        metadata={k: v for k, v in metadata.items() if v is not None},
        trace_mode=trace_mode,
        parent=parent,
    ) as span:
        set_span_attr(span, "rag.query_length", len(query))
        set_span_attr(span, "rag.output_length", len(answer))
        set_span_attr(span, "rag.chunks_used", len(chunks))

        if "retrieval_mode" in trace_info:
            set_span_attr(span, "rag.retrieval_mode", trace_info["retrieval_mode"])
        if "rerank_enabled" in trace_info:
            set_span_attr(span, "rag.rerank_enabled", bool(trace_info["rerank_enabled"]))
        if "generation_model" in trace_info:
            set_span_attr(span, "rag.generation_model", trace_info["generation_model"])

        for key, val in latency_ms.items():
            if val is not None:
                set_span_attr(span, f"latency.{key}", val)

        for metric, score in scores.items():
            if score is not None:
                try:
                    set_span_attr(span, f"eval.{metric}", float(score))
                except (TypeError, ValueError):
                    set_span_attr(span, f"eval.{metric}", str(score))

    if flush:
        force_flush()


# A long conversation would otherwise put an unbounded string on the span. The limit is high
# enough for a realistic session and low enough that no backend rejects the span.
MAX_TRANSCRIPT_CHARS = 60_000


@contextmanager
def rag_turn_span(
    *,
    question: str,
    answer: str,
    turn_index: int,
    session_id: str | None = None,
    tags: Sequence[str] | None = None,
    trace_mode: str = TRACE_MODE_PROD,
    name: str = "rag.chat.turn",
) -> Iterator[trace.Span]:
    """One question and its answer, as a child of the span that is already active.

    This is what makes a session trace readable: the root span is the conversation, and each
    turn hangs off it carrying its own input and output.

    The session id and the tags are repeated on every turn. Langfuse filters and aggregates
    on a trace attribute it finds on the span in front of it, so a value that lives only on
    the root is invisible on the children.
    """
    with get_tracer().start_as_current_span(name) as span:
        _apply_turn_attributes(
            span,
            session_id=session_id,
            message_id=None,
            query=question,
            answer=answer,
            observation_type="generation",
            model=None,
            metadata=None,
            trace_mode=trace_mode,
        )
        set_span_attr(span, "rag.turn.index", turn_index)
        set_span_tags(span, tags or [])
        yield span


def emit_session_trace(
    *,
    session_id: str,
    turns: Sequence[tuple[str, str]],
    trace_mode: str = TRACE_MODE_PROD,
    tags: Sequence[str] | None = None,
    attributes: dict[str, Any] | None = None,
    label: str | None = None,
    flush: bool = True,
) -> tuple[str | None, int]:
    """Emit one trace that holds every question and answer of a session.

    The root span is the conversation. Each turn is a child span, so the whole session reads
    as a single trace rather than a list of unrelated ones. The session id goes on the root
    as well, so the backends also group this trace with the per-turn traces of the session.

    Returns the hex trace id and the number of turns written, so the caller can report what
    it sent.
    """
    root_query = turns[0][0] if turns else None
    root_answer = turns[-1][1] if turns else None

    trace_id: str | None = None
    with rag_pipeline_span(
        "rag.session",
        session_id=session_id,
        query=root_query,
        answer=root_answer,
        observation_type="chain",
        metadata={"turns": len(turns), "session_label": label},
        trace_mode=trace_mode,
        tags=tags or [],
        attributes=attributes or {},
    ) as span:
        set_span_attr(span, "rag.session.turns", len(turns))
        set_span_attr(
            span,
            "rag.session.transcript",
            json.dumps(
                [{"question": q, "answer": a} for q, a in turns], ensure_ascii=False
            )[:MAX_TRANSCRIPT_CHARS],
        )
        for index, (question, answer) in enumerate(turns, start=1):
            with rag_turn_span(
                question=question,
                answer=answer,
                turn_index=index,
                session_id=session_id,
                tags=tags or [],
                trace_mode=trace_mode,
            ):
                pass

        context = span.get_span_context()
        if context is not None and context.is_valid:
            trace_id = format(context.trace_id, "032x")

    if flush:
        force_flush()
    return trace_id, len(turns)
