import logging
import os
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

_tracer: Any | None = None
_provider: Any | None = None
_initialized = False


def _parse_resource_attributes(raw: str) -> dict[str, str]:
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
    return out


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw:
        return headers
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            headers[k.strip()] = unquote(v.strip())
    return headers


def _traces_endpoint(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        return base
    return f"{base}/v1/traces"


def init_tracing() -> None:
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

    if HAVE_HTTPX_OTEL:
        HTTPXClientInstrumentor().instrument()
    _initialized = True
    logger.info("OpenTelemetry tracing initialized service=%s", service_name)


def get_tracer() -> Any:
    global _tracer
    if not _initialized:
        init_tracing()
    if _tracer is None and HAVE_OTEL and trace:
        _tracer = trace.get_tracer(os.getenv("OTEL_SERVICE_NAME", "rag-platform"))
    return _tracer
