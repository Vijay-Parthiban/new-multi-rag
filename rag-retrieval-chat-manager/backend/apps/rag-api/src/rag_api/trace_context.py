"""The pipeline and Knowledge Product records, packed for a trace.

Both trace backends need the same thing on a span: what the turn actually ran on. Those
records live in the ingestion database, so this module reads them and flattens them into span
attributes.

The data is fetched from the ingestion service rather than taken from the request. A client
could otherwise label its own trace with a pipeline it did not use, and the label would then
disagree with what ran.

Everything here is best effort. A trace without context is better than a failed answer, so an
unreachable ingestion service logs a warning and returns nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from rag_core.assistant import session_memory_for_product
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

# One attribute value cannot be unbounded: the record plus its destination configs is a few
# kilobytes, and a whole pipeline record is well under this.
MAX_JSON_CHARS = 8_000

# Langfuse puts an attribute it does not recognise into a catch-all that cannot be filtered.
# The fields worth filtering on are therefore also written with the prefix it does index.
_FILTERABLE = "langfuse.trace.metadata."


def _pack(value: Any) -> str:
    """JSON for an attribute, never longer than the limit."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text[:MAX_JSON_CHARS]


def flatten(pipeline: dict[str, Any], product: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten the two records into span attributes.

    Three forms of each fact are written, because the backends read different ones:

    * a bare ``metadata`` JSON string, which is where Arize looks for user-defined values
    * ``rag.*`` scalars and JSON blobs, which any reader can use without parsing
    * ``langfuse.trace.metadata.*`` copies, which Langfuse alone can filter on
    """
    product = product or {}
    destinations = product.get("destinations") or []
    enabled_destinations = [
        str(d.get("destination_type")) for d in destinations if d.get("enabled")
    ]

    pipeline_summary = {
        "id": pipeline.get("id"),
        "name": pipeline.get("name"),
        "slug": pipeline.get("slug"),
        "description": pipeline.get("description"),
        "rag_strategy": pipeline.get("rag_strategy"),
        "chat_model": pipeline.get("chat_model"),
        "modality_mode": pipeline.get("modality_mode"),
        "prompt_template_id": pipeline.get("prompt_template_id"),
        "guardrails_config_id": pipeline.get("guardrails_config_id"),
        "model_settings": pipeline.get("model_settings"),
    }
    product_summary = {
        "id": product.get("id"),
        "name": product.get("name"),
        "status": product.get("status"),
        "chunk_strategy": product.get("chunk_strategy"),
        "modality_mode": product.get("modality_mode"),
        "text_embedding_model": product.get("text_embedding_model"),
        "sparse_embedding_model": product.get("sparse_embedding_model"),
        "enabled_destinations": enabled_destinations,
    }

    attributes: dict[str, Any] = {
        # Arize reads user-defined values from a single `metadata` attribute.
        "metadata": _pack({"pipeline": pipeline_summary, "knowledge_product": product_summary}),
        # The complete records, so nothing about the configuration is lost.
        "rag.pipeline": _pack(pipeline),
        "rag.knowledge_product": _pack(product),
        # Scalars, for a reader that does not want to parse JSON.
        "rag.pipeline.id": pipeline.get("id"),
        "rag.pipeline.name": pipeline.get("name"),
        "rag.pipeline.slug": pipeline.get("slug"),
        "rag.pipeline.strategy": pipeline.get("rag_strategy"),
        "rag.pipeline.chat_model": pipeline.get("chat_model"),
        "rag.knowledge_product.id": product.get("id"),
        "rag.knowledge_product.name": product.get("name"),
        "rag.knowledge_product.status": product.get("status"),
        "rag.knowledge_product.chunk_strategy": product.get("chunk_strategy"),
        "rag.knowledge_product.destinations": ",".join(enabled_destinations),
        "rag.knowledge_product.text_embedding_model": product.get("text_embedding_model"),
    }

    # Filterable copies for Langfuse. Values must be strings there.
    filterable = {
        "pipeline_id": pipeline.get("id"),
        "pipeline_name": pipeline.get("name"),
        "pipeline_slug": pipeline.get("slug"),
        "pipeline_strategy": pipeline.get("rag_strategy"),
        "chat_model": pipeline.get("chat_model"),
        "knowledge_product_id": product.get("id"),
        "knowledge_product_name": product.get("name"),
        "chunk_strategy": product.get("chunk_strategy"),
        "enabled_destinations": ", ".join(enabled_destinations),
    }
    for key, value in filterable.items():
        if value is not None:
            attributes[_FILTERABLE + key] = str(value)

    return {key: value for key, value in attributes.items() if value is not None}


def _headers(settings: Settings) -> dict[str, str]:
    api_key = getattr(settings, "api_key", "") or ""
    return {"X-API-Key": api_key} if api_key else {}


def fetch_context(settings: Settings, pipeline_id: str | None) -> dict[str, Any]:
    """The flattened attributes for one pipeline. Empty when it cannot be read."""
    if not pipeline_id:
        return {}

    base = (getattr(settings, "ingestion_service_url", "") or "").rstrip("/")
    if not base:
        return {}

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                f"{base}/api/pipelines/{pipeline_id}", headers=_headers(settings)
            )
            if response.status_code != 200:
                logger.warning(
                    "trace context: pipeline %s answered %s", pipeline_id, response.status_code
                )
                return {}

            pipeline = response.json()
            product = pipeline.get("knowledge_product") or {}
            product_id = pipeline.get("knowledge_product_id") or product.get("id")

            # The pipeline embeds a summary of its product. The detail carries the
            # destination configs, which is the part worth recording.
            if product_id:
                detail = client.get(
                    f"{base}/api/knowledge-products/{product_id}", headers=_headers(settings)
                )
                if detail.status_code == 200:
                    product = detail.json()
    except Exception as exc:  # noqa: BLE001 - a trace must not fail the turn
        logger.warning("trace context: fetch failed pipeline=%s error=%s", pipeline_id, exc)
        return {}

    return flatten(pipeline, product)


async def fetch_context_async(settings: Settings, pipeline_id: str | None) -> dict[str, Any]:
    """`fetch_context` without blocking the event loop.

    The streaming route is async and the fetch is two blocking HTTP calls. Running it in a
    worker thread keeps one slow ingestion response from stalling every other stream.
    """
    if not pipeline_id:
        return {}
    return await asyncio.to_thread(fetch_context, settings, pipeline_id)


def memory_for_pipeline(settings: Settings, pipeline_id: str | None) -> tuple[str, int] | None:
    """The session-memory prefix and TTL of a pipeline, or None when Redis is off.

    This is the same gate the chat route applies, read from the Knowledge Product's
    destinations, so a session trace is emitted exactly when a session existed.
    """
    if not pipeline_id:
        return None

    base = (getattr(settings, "ingestion_service_url", "") or "").rstrip("/")
    if not base:
        return None

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                f"{base}/api/pipelines/{pipeline_id}", headers=_headers(settings)
            )
            if response.status_code != 200:
                return None
            product = response.json().get("knowledge_product") or {}
            product_id = product.get("id")
            if product_id:
                detail = client.get(
                    f"{base}/api/knowledge-products/{product_id}", headers=_headers(settings)
                )
                if detail.status_code == 200:
                    product = detail.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("session memory: fetch failed pipeline=%s error=%s", pipeline_id, exc)
        return None

    return session_memory_for_product(product.get("destinations") or [])
