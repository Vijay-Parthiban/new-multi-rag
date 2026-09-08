import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import unquote

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

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


def init_tracing() -> None:
    """Configure the global TracerProvider and OTLP HTTP exporter → collector."""
    global _tracer, _provider, _initialized
    if _initialized:
        return

    enabled = os.getenv("OTEL_TRACING_ENABLED", "true").lower() == "true"
    service_name = os.getenv("OTEL_SERVICE_NAME", "rag-platform")

    if not enabled:
        logger.info("OpenTelemetry tracing is disabled")
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
) -> Iterator[trace.Span]:
    """
    Create a root RAG span with Langfuse-recognized attributes.

    Langfuse maps:
      langfuse.session.id, langfuse.observation.input/output,
      langfuse.trace.input/output, langfuse.observation.type, …
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=trace.SpanKind.SERVER) as span:
        set_span_attr(span, "langfuse.observation.type", observation_type)
        if session_id:
            set_span_attr(span, "langfuse.session.id", session_id)
        if message_id:
            set_span_attr(span, "langfuse.observation.metadata.message_id", message_id)
        if query is not None:
            set_span_attr(span, "langfuse.trace.input", query)
            set_span_attr(span, "langfuse.observation.input", query)
            set_span_attr(span, "input.value", query)
        if answer is not None:
            set_span_attr(span, "langfuse.trace.output", answer)
            set_span_attr(span, "langfuse.observation.output", answer)
            set_span_attr(span, "output.value", answer)
        if model:
            set_span_attr(span, "langfuse.observation.model.name", model)
            set_span_attr(span, "gen_ai.request.model", model)
        if metadata:
            for key, val in metadata.items():
                set_span_attr(span, f"langfuse.observation.metadata.{key}", val)
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
) -> None:
    """
    Emit a synthetic post-hoc RAG pipeline span (used by eval-worker after metrics).

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
        "rag.pipeline",
        session_id=session_id,
        message_id=message_id,
        query=query,
        answer=answer,
        observation_type="generation",
        model=trace_info.get("generation_model"),
        metadata={k: v for k, v in metadata.items() if v is not None},
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
