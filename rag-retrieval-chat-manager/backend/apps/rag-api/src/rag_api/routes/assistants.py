"""Assistant endpoints.

An assistant is a pipeline on the ingestion side. This module resolves it by
slug, finds the stores of the Knowledge Product it reads, and delegates to the
existing chat handlers, so guardrails, retrieval, rerank, generation,
persistence and metrics stay in one place.

Two surfaces, both derived from the same slug:

* ``POST /api/assistants/{slug}/chat`` and ``/chat/stream`` — the native shape.
* ``POST /v1/assistants/{slug}/chat/completions`` — the OpenAI shape, so an
  OpenAI SDK client pointed at ``{base}/v1/assistants/{slug}`` works with no
  adapter code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from rag_api.session_close import SessionNotFound, close_session
from rag_core.assistant import (
    STRATEGY_LABELS,
    StrategyUnavailable,
    resolve_strategy,
    session_memory_for_product,
    stores_for_product,
    strategies_for_product,
)
from rag_core.session_memory import SessionMemory, SessionMemoryUnavailable
from rag_db.repositories.prompt_repository import PromptRepository
from rag_db.services.database import get_session_factory
from rag_core.schemas import ModelSettings
from rag_shared.config import Settings
from rag_shared.tracing import TRACE_MODE_HEADER, normalize_trace_mode
from rag_shared.types import SearchMode

from rag_api.routes.chat import ChatRequest, ChatResponse, chat, chat_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistants"])

_INGESTION_TIMEOUT_S = 10.0
_STREAM_MEDIA_TYPE = "text/event-stream"


class AssistantChatRequest(BaseModel):
    """A question for one assistant pipeline."""

    query: str = Field(..., description="The user question.")
    session_id: uuid.UUID | None = Field(default=None, description="Continue an existing session.")
    guardrails_config_id: uuid.UUID | None = Field(
        default=None, description="Overrides the pipeline's guardrails config for this request."
    )
    prompt_template_id: uuid.UUID | None = Field(
        default=None, description="Overrides the pipeline's prompt template for this request."
    )
    model_settings: ModelSettings | None = Field(
        default=None, description="Overrides the pipeline's model settings for this request."
    )
    retrieval_mode: SearchMode | None = None
    retrieve_limit: int | None = Field(default=None, ge=1, le=50)
    rerank_enabled: bool | None = None
    rerank_model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)


class OpenAIMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None


class OpenAIChatRequest(BaseModel):
    """The subset of the OpenAI chat-completions body this endpoint honours."""

    model: str | None = None
    messages: list[OpenAIMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    user: str | None = None
    # OpenAI defines no session field. This extension carries the memory key, and
    # `user` is the fallback so a client that already sends a stable id gets memory
    # without changing anything.
    session_id: str | None = None


def _session_uuid(explicit: str | None, fallback: str | None) -> uuid.UUID | None:
    """Resolve the session key from an OpenAI body.

    An explicit `session_id` that is not a UUID is rejected, because the caller
    asked for memory and would otherwise silently get none. A `user` that is not a
    UUID is ignored: it is an abuse-tracking field, and failing on it would break
    clients that never intended it as a session.
    """
    if explicit:
        try:
            return uuid.UUID(explicit)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_SESSION_ID",
                    "message": f"session_id must be a UUID, got '{explicit[:64]}'.",
                },
            ) from exc
    if fallback:
        try:
            return uuid.UUID(fallback)
        except ValueError:
            logger.debug("openai_user_is_not_a_session_id user=%s", fallback[:64])
    return None


def _headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.api_key} if settings.api_key else {}


def _last_user_message(messages: list[OpenAIMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # OpenAI allows a list of parts; only the text parts carry a question.
            text = " ".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""


async def _resolve_assistant(request: Request, slug: str) -> dict[str, Any]:
    """Fetch the pipeline by slug and resolve the stores its strategy reads."""
    settings: Settings = request.app.state.settings
    base = settings.ingestion_service_url.rstrip("/")
    url = f"{base}/api/pipelines/by-slug/{slug}"
    try:
        async with httpx.AsyncClient(timeout=_INGESTION_TIMEOUT_S) as client:
            response = await client.get(url, headers=_headers(settings))
    except httpx.RequestError as exc:
        logger.error("assistant resolve failed slug=%s error=%s", slug, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "INGESTION_SERVICE_UNAVAILABLE",
                "message": f"Cannot reach the ingestion service: {exc}",
            },
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail={"code": "ASSISTANT_NOT_FOUND", "message": f"No assistant has the slug '{slug}'."},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail={"code": "INGESTION_SERVICE_ERROR", "message": response.text[:500]},
        )

    pipeline = response.json()
    if not pipeline.get("is_assistant"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NOT_AN_ASSISTANT",
                "message": (
                    f"Pipeline '{slug}' is an ingestion pipeline. An assistant reads a "
                    "Knowledge Product, so its strategy must be vector, lexical, relational or hybrid."
                ),
            },
        )

    destinations = (pipeline.get("knowledge_product") or {}).get("destinations") or []
    stores = stores_for_product(destinations)
    try:
        resolve_strategy(pipeline["rag_strategy"], stores)
    except StrategyUnavailable as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RAG_STRATEGY_UNAVAILABLE",
                "message": str(exc),
                "missing_destinations": exc.missing,
            },
        )

    pipeline["_stores"] = stores
    pipeline["_strategies"] = strategies_for_product(destinations)
    pipeline["_session_memory"] = session_memory_for_product(destinations)
    return pipeline


def _system_prompt_for(
    settings: Settings, pipeline: dict[str, Any], override_id: Any = None
) -> str | None:
    """The system message for this turn.

    A request-level template wins, so the Chat page can try a different one
    without editing the pipeline, the same way it can try a guardrails config.
    """
    template_id = override_id or pipeline.get("prompt_template_id")
    if not template_id:
        return None
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        template = PromptRepository(db).get(uuid.UUID(str(template_id)))
    if not template:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PROMPT_TEMPLATE_NOT_FOUND",
                "message": f"Prompt template {template_id} no longer exists.",
            },
        )
    return template.content


async def _build_chat_request(
    request: Request, slug: str, body: AssistantChatRequest
) -> ChatRequest:
    """Turn an assistant request into the flat request the chat handler takes."""
    settings: Settings = request.app.state.settings
    pipeline = await _resolve_assistant(request, slug)
    stores = pipeline["_stores"]
    product = pipeline.get("knowledge_product") or {}

    # The dense store is the only vector search the fanout collections support.
    retrieval_mode = body.retrieval_mode or SearchMode.DENSE
    if stores.qdrant_collection is None and retrieval_mode is SearchMode.HYBRID:
        retrieval_mode = SearchMode.DENSE

    return ChatRequest(
        query=body.query,
        session_id=body.session_id,
        retrieval_mode=retrieval_mode,
        retrieve_limit=body.retrieve_limit or settings.retrieve_limit,
        rerank_enabled=body.rerank_enabled if body.rerank_enabled is not None else settings.reranker_enabled,
        rerank_model=body.rerank_model,
        top_k=body.top_k or settings.rerank_top_k,
        generation_model=pipeline.get("chat_model") or settings.chat_model,
        collection=stores.qdrant_collection,
        embedding_model=product.get("text_embedding_model") or settings.embedding_model,
        system_prompt=_system_prompt_for(settings, pipeline, body.prompt_template_id),
        # Absent when this pipeline has no saved settings, which leaves the
        # service defaults in charge.
        model_settings=body.model_settings or _pipeline_model_settings(pipeline),
        strategy=pipeline["rag_strategy"],
        stores=stores,
        # Absent when the product has no enabled Redis destination, which is what
        # makes the turn stateless.
        session_memory_prefix=(pipeline.get("_session_memory") or (None, None))[0],
        session_memory_ttl_s=(pipeline.get("_session_memory") or (None, None))[1],
        # A request-level guardrails config wins, so the Chat page can try a
        # different one without editing the pipeline.
        guardrails_config_id=body.guardrails_config_id or _as_uuid(pipeline.get("guardrails_config_id")),
        # Taken from the pipeline that was just resolved, not from the request, so the trace
        # context always describes the pipeline that actually ran.
        pipeline_id=str(pipeline["id"]) if pipeline.get("id") else None,
    )


def _as_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _pipeline_model_settings(pipeline: dict[str, Any]) -> ModelSettings | None:
    """The pipeline's saved sampling settings, or None when it has none.

    The ingestion manager stores these as JSON, so a malformed value is dropped
    rather than failing the turn. Returning None leaves the service defaults in
    charge, which is how an unconfigured pipeline behaved before this existed.
    """
    raw = pipeline.get("model_settings")
    if not raw:
        return None
    try:
        return ModelSettings(**raw)
    except Exception:  # noqa: BLE001 - bad saved data must not break a chat turn
        logger.warning(
            "ignoring malformed model_settings slug=%s", pipeline.get("slug")
        )
        return None


@router.get("/api/assistants/{slug}")
async def get_assistant(slug: str, request: Request) -> dict[str, Any]:
    """The resolved configuration, for an integrator to read. No secrets."""
    settings: Settings = request.app.state.settings
    pipeline = await _resolve_assistant(request, slug)
    stores = pipeline["_stores"]
    product = pipeline.get("knowledge_product") or {}
    memory = pipeline.get("_session_memory")
    return {
        "slug": pipeline["slug"],
        "name": pipeline["name"],
        "description": pipeline["description"],
        "chat_model": pipeline.get("chat_model") or settings.chat_model,
        "strategy": pipeline["rag_strategy"],
        "strategies_available": [
            {"id": s, "label": STRATEGY_LABELS[s][0], "description": STRATEGY_LABELS[s][1]}
            for s in pipeline["_strategies"]
        ],
        "knowledge_product": {
            "id": product.get("id"),
            "name": product.get("name"),
            "status": product.get("status"),
            "chunk_strategy": product.get("chunk_strategy"),
            "text_embedding_model": product.get("text_embedding_model"),
        },
        "stores": stores.model_dump(),
        "prompt_template_id": pipeline.get("prompt_template_id"),
        "guardrails_config_id": pipeline.get("guardrails_config_id"),
        "session_memory": {
            "enabled": memory is not None,
            "ttl_seconds": memory[1] if memory else None,
            "reason": None
            if memory
            else "The Knowledge Product has no enabled Redis destination.",
        },
        "endpoints": {
            "chat": f"/api/assistants/{slug}/chat",
            "chat_stream": f"/api/assistants/{slug}/chat/stream",
            "openai_base_url": f"/v1/assistants/{slug}",
            "session_get": f"/api/assistants/{slug}/sessions/{{session_id}}",
            "session_end": f"/api/assistants/{slug}/sessions/{{session_id}}",
        },
    }


@router.post("/api/assistants/{slug}/chat", response_model=ChatResponse)
async def assistant_chat(
    slug: str, body: AssistantChatRequest, request: Request
) -> ChatResponse:
    built = await _build_chat_request(request, slug, body)
    # The chat handler is synchronous: retrieval and generation take seconds, so
    # keep them off the event loop.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, chat, request, built)


@router.post("/api/assistants/{slug}/chat/stream")
async def assistant_chat_stream(slug: str, body: AssistantChatRequest, request: Request):
    built = await _build_chat_request(request, slug, body)
    return await chat_stream(request, built)


def _memory_for(pipeline: dict[str, Any], settings: Settings) -> SessionMemory:
    """The session memory of this assistant, or 422 when the product has no Redis."""
    memory = pipeline.get("_session_memory")
    if not memory:
        product = (pipeline.get("knowledge_product") or {}).get("name")
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SESSION_MEMORY_UNAVAILABLE",
                "message": (
                    f"Assistant '{pipeline['slug']}' has no session memory because "
                    f"'{product or 'its Knowledge Product'}' has no enabled Redis destination. "
                    "Enable it in the Ingestion Manager."
                ),
            },
        )
    return SessionMemory(settings, prefix=memory[0], ttl_s=memory[1])


@router.get("/api/assistants/{slug}/sessions/{session_id}")
async def get_assistant_session(
    slug: str, session_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    """What this assistant remembers for one session.

    Read-only, and safe to call on a session that does not exist: `exists` is then
    false and `turns` is 0.
    """
    settings: Settings = request.app.state.settings
    pipeline = await _resolve_assistant(request, slug)
    return _memory_for(pipeline, settings).inspect(str(session_id))


@router.delete("/api/assistants/{slug}/sessions/{session_id}", status_code=204)
async def end_assistant_session(
    slug: str, session_id: uuid.UUID, request: Request
) -> Response:
    """End the session and drop everything it remembered.

    This is the only way to clear memory, and it is idempotent: ending a session
    that already expired, or ending one twice, still answers 204. A caller may
    therefore retry a failed end without checking first.
    """
    settings: Settings = request.app.state.settings
    pipeline = await _resolve_assistant(request, slug)
    memory = _memory_for(pipeline, settings)
    try:
        memory.clear(str(session_id))
    except SessionMemoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SESSION_MEMORY_UNAVAILABLE",
                "message": f"Redis refused the request: {exc}",
            },
        ) from exc
    return Response(status_code=204)


@router.post("/api/assistants/{slug}/sessions/{session_id}/close")
async def close_assistant_session(
    slug: str, session_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    """End a session from the pipeline endpoint, which is the production path.

    The pipeline comes from the slug, so a caller names one thing and the export always
    describes the pipeline that actually served the conversation. The trace mode comes from the
    usual header, and a caller that sends none is production.

    The work lives in `session_close.close_session`: write the conversation out as one trace,
    then drop what it remembered. It runs in a worker thread, because it does blocking
    database, Redis and HTTP work and this handler is async.
    """
    settings: Settings = request.app.state.settings
    pipeline = await _resolve_assistant(request, slug)
    try:
        return await asyncio.to_thread(
            close_session,
            settings,
            session_id,
            pipeline_id=str(pipeline["id"]) if pipeline.get("id") else None,
            trace_mode=normalize_trace_mode(request.headers.get(TRACE_MODE_HEADER)),
        )
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


def _openai_chunk(slug: str, chunk_id: str, created: int, *, content: str | None = None, finish: str | None = None) -> str:
    payload: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": slug,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
    }
    if content is not None:
        payload["choices"][0]["delta"] = {"content": content}
    return f"data: {json.dumps(payload)}\n\n"


def _openai_stream(slug: str, inner: StreamingResponse):
    """Translate the native SSE frames into OpenAI chat-completion chunks."""

    async def generate():
        chunk_id = f"chatcmpl-{uuid.uuid4()}"
        created = int(time.time())
        answer_parts: list[str] = []
        async for frame in inner.body_iterator:
            text = frame.decode("utf-8", "replace") if isinstance(frame, bytes) else str(frame)
            for line in text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                kind = payload.get("type")
                if kind == "token" and payload.get("content"):
                    answer_parts.append(payload["content"])
                    yield _openai_chunk(slug, chunk_id, created, content=payload["content"])
                elif kind in {"done", "blocked"}:
                    # A blocked turn never streamed tokens, so its answer arrives
                    # whole and is emitted as one chunk.
                    content = payload.get("content")
                    if content and not answer_parts:
                        yield _openai_chunk(slug, chunk_id, created, content=content)
                    elif kind == "done" and not answer_parts:
                        answer = (payload.get("metadata") or {}).get("answer")
                        if answer:
                            yield _openai_chunk(slug, chunk_id, created, content=answer)
                elif kind == "error":
                    yield f'data: {json.dumps({"error": {"message": payload.get("content") or "stream failed", "type": "server_error"}})}\n\n'
                    yield "data: [DONE]\n\n"
                    return
        yield _openai_chunk(slug, chunk_id, created, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type=_STREAM_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/v1/assistants/{slug}/chat/completions")
async def assistant_openai_completions(slug: str, body: OpenAIChatRequest, request: Request):
    """The OpenAI chat-completions shape, so an SDK client needs no adapter."""
    query = _last_user_message(body.messages)
    if not query:
        return {
            "error": {
                "message": "No user message with text content was found.",
                "type": "invalid_request_error",
                "code": "MISSING_USER_MESSAGE",
            }
        }

    built = await _build_chat_request(
        request,
        slug,
        AssistantChatRequest(
            query=query,
            session_id=_session_uuid(body.session_id, body.user),
        ),
    )

    if body.stream:
        inner = await chat_stream(request, built)
        return _openai_stream(slug, inner)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, chat, request, built)
    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": slug,
        # Not part of the OpenAI shape. It lets a client that did not send an id
        # learn the session it just used, so the next turn can continue it.
        "session_id": str(result.session_id),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
