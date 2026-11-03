"""Read chat turns out of an OTLP/JSON trace export.

The OpenTelemetry Collector posts every turn span here (`traces/feedback` pipeline). Only
the two turn span names are kept; any other span in the batch is ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from rag_shared.tracing import normalize_trace_mode

TURN_SPAN_NAMES = frozenset({"rag.chat", "rag.chat.stream"})
MAX_TEXT = 20_000
_GUARD_PHASES = ("input", "retrieval", "output")


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    """OTLP/JSON `[{key, value: {stringValue|intValue|boolValue|doubleValue}}]` as a dict."""
    out: dict[str, Any] = {}
    for item in span.get("attributes") or []:
        value = item.get("value") or {}
        if "stringValue" in value:
            out[item["key"]] = value["stringValue"]
        elif "intValue" in value:
            out[item["key"]] = int(value["intValue"])  # OTLP/JSON writes int64 as a string
        elif "boolValue" in value:
            out[item["key"]] = bool(value["boolValue"])
        elif "doubleValue" in value:
            out[item["key"]] = float(value["doubleValue"])
    return out


def _uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def parse_turn_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """`ConversationTurn` column dicts for each complete turn span in the payload."""
    records: list[dict[str, Any]] = []
    for resource in payload.get("resourceSpans") or []:
        for scope in resource.get("scopeSpans") or []:
            for span in scope.get("spans") or []:
                if span.get("name") not in TURN_SPAN_NAMES:
                    continue
                attrs = _attrs(span)
                session_id = attrs.get("session.id") or attrs.get("langfuse.session.id")
                question = attrs.get("input.value")
                answer = attrs.get("output.value")
                # A turn that errored has no answer; there is nothing to review.
                if not (session_id and question and answer):
                    continue
                records.append(
                    {
                        "trace_id": span["traceId"],
                        "span_id": span["spanId"],
                        "session_id": str(session_id),
                        "pipeline_slug": attrs.get("rag.pipeline.slug") or None,
                        "trace_mode": normalize_trace_mode(attrs.get("rag.trace_mode")),
                        "question": str(question)[:MAX_TEXT],
                        "answer": str(answer)[:MAX_TEXT],
                        "message_id": _uuid(
                            attrs.get("langfuse.observation.metadata.message_id")
                            or attrs.get("rag.message_id")
                        ),
                        "blocked": any(attrs.get(f"guardrails.{p}.blocked") is True for p in _GUARD_PHASES),
                        "chunks_used": attrs.get("rag.chunks_used"),
                        "model": attrs.get("gen_ai.request.model"),
                        "started_at": datetime.fromtimestamp(
                            int(span["startTimeUnixNano"]) / 1e9, tz=timezone.utc
                        ),
                    }
                )
    return records
