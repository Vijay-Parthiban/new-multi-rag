from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from rag_core import PipelineRequest
from rag_db.models.chat import ChatPipelineTrace
from rag_db.repositories.chat_repository import ChatRepository
from rag_db.repositories.guardrails_repository import GuardrailsRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings
from rag_shared.guardrails_client import run_guardrails_check, check_blocked

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(PipelineRequest):
    session_id: uuid.UUID | None = None
    guardrails_config_id: uuid.UUID | None = None


class SourceCitation(BaseModel):
    source_locator: str
    chunk_index: int
    rerank_score: float


class ChatResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    answer: str
    sources: list[SourceCitation]
    trace_id: uuid.UUID | None = None
    metrics_status: str


class MetricsResponse(BaseModel):
    message_id: uuid.UUID
    status: str
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    kendall_tau: float | None = None
    mrr: float | None = None
    ndcg: float | None = None
    metrics: dict | None = None
    error_message: str | None = None


class ChatStatItem(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    query: str | None = None
    answer: str
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    kendall_tau: float | None = None
    mrr: float | None = None
    ndcg: float | None = None
    metrics: dict | None = None
    metrics_status: str
    computed_at: str | None = None
    latency_ms: dict | None = None
    retrieval_mode: str | None = None
    rerank_enabled: bool | None = None
    generation_model: str | None = None
    created_at: str | None = None


class ChatStatsResponse(BaseModel):
    limit: int
    count: int
    items: list[ChatStatItem]


class ChatSessionItem(BaseModel):
    session_id: uuid.UUID
    created_at: str | None = None
    last_message_at: str | None = None
    preview: str | None = None
    message_count: int = 0


class ChatSessionsResponse(BaseModel):
    limit: int
    count: int
    items: list[ChatSessionItem]


class MessageTraceInfo(BaseModel):
    retrieval_mode: str | None = None
    rerank_enabled: bool | None = None
    generation_model: str | None = None
    route: str | None = None  # "normal", "self_corrective", "self_corrective_auto", "greeting", "blocked"


class ChatMessageItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: str | None = None
    trace: MessageTraceInfo | None = None
    sources: list[SourceCitation] = []
    metrics_status: str | None = None
    blocked: bool = False
    blocked_by_guard: str | None = None
    blocked_on: str | None = None


GUARD_BLOCK_COPY = {
    "ban_list": {
        "title": "Banned keyword",
        "input": "This message was blocked because it contains a banned word or phrase.",
        "output": "The generated answer was blocked because it contains a banned word or phrase.",
    },
    "pii_check": {
        "title": "Personal information",
        "input": "This message was blocked because it appears to contain personal identifiable information.",
        "output": "The generated answer was blocked because it appears to contain personal identifiable information.",
    },
    "toxic_language": {
        "title": "Toxic language",
        "input": "This message was blocked because it contains toxic or harmful language.",
        "output": "The generated answer was blocked because it contains toxic or harmful language.",
    },
}


def _blocked_answer(guard: str | None, phase: str) -> str:
    info = GUARD_BLOCK_COPY.get(guard or "", {})
    return info.get(phase) or f"{phase.capitalize()} blocked by guardrail: {guard or 'unknown'}."


def _blocked_latency(guard: str | None, phase: str) -> dict:
    return {
        "route": "blocked",
        "blocked": True,
        "blocked_by_guard": guard,
        "blocked_on": phase,
    }


def _blocked_payload(
    *,
    content: str,
    guard: str | None,
    phase: str,
    session_id: uuid.UUID,
    message_id: uuid.UUID,
) -> dict:
    info = GUARD_BLOCK_COPY.get(guard or "", {})
    return {
        "type": "blocked",
        "content": content,
        "blocked_by_guard": guard,
        "blocked_on": phase,
        "blocked_title": info.get("title", guard or "Guardrail"),
        "session_id": str(session_id),
        "message_id": str(message_id),
        "route": "blocked",
        "metrics_status": "skipped",
    }


class ChatSessionMessagesResponse(BaseModel):
    session_id: uuid.UUID
    count: int
    items: list[ChatMessageItem]


class DeleteMessageResponse(BaseModel):
    session_id: uuid.UUID
    deleted_message_ids: list[uuid.UUID]


def _sources_from_trace(trace: ChatPipelineTrace | None) -> list[SourceCitation]:
    if trace is None or not trace.reranked_chunks:
        return []
    return [
        SourceCitation(
            source_locator=chunk["source_locator"],
            chunk_index=chunk["chunk_index"],
            rerank_score=chunk["rerank_score"],
        )
        for chunk in trace.reranked_chunks
    ]


def _staged_metrics(raw: dict | None) -> dict | None:
    if not raw:
        return None
    if "retrieval" in raw or "reranker" in raw or "generation" in raw:
        return raw
    return None


def _reranker_metric(raw: dict | None, key: str) -> float | None:
    staged = _staged_metrics(raw)
    if not staged:
        return None
    value = (staged.get("reranker") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _build_metrics_response(message_id: uuid.UUID, metrics) -> MetricsResponse:
    raw = metrics.raw_ragas if isinstance(metrics.raw_ragas, dict) else None
    staged = _staged_metrics(raw)
    return MetricsResponse(
        message_id=message_id,
        status=metrics.status,
        faithfulness=metrics.faithfulness,
        answer_relevancy=metrics.answer_relevancy,
        context_precision=metrics.context_precision,
        context_recall=metrics.context_recall,
        kendall_tau=_reranker_metric(raw, "kendall_tau"),
        mrr=_reranker_metric(raw, "mrr"),
        ndcg=_reranker_metric(raw, "ndcg"),
        metrics=staged,
        error_message=metrics.error_message,
    )


def _persist_chat_turn(
    *,
    settings: Settings,
    queue,
    session_id: uuid.UUID | None,
    source_type: str | None,
    source_id: str | None,
    query: str,
    answer: str,
    retrieval_mode: str,
    retrieve_limit: int,
    rerank_enabled: bool,
    rerank_model: str | None,
    generation_model: str,
    retrieved_chunks: list | None = None,
    reranked_chunks: list | None = None,
    latency_ms: dict | None = None,
    save_trace: bool = True,
    enqueue_metrics: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None, str]:
    """
    Persist user+assistant messages and optional pipeline trace/metrics job.
    Returns (session_id, assistant_message_id, trace_id|None, metrics_status).
    """
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        if session_id and repo.get_session(session_id):
            sid = session_id
        else:
            session = repo.create_session(source_type=source_type, source_id=source_id)
            sid = session.id

        repo.add_message(sid, "user", query)
        assistant_msg = repo.add_message(sid, "assistant", answer)

        trace_id: uuid.UUID | None = None
        metrics_status = "skipped"
        if save_trace:
            trace_db = repo.save_pipeline_trace(
                assistant_msg.id,
                query=query,
                retrieval_mode=retrieval_mode,
                retrieve_limit=retrieve_limit,
                rerank_enabled=rerank_enabled,
                rerank_model=rerank_model,
                generation_model=generation_model,
                retrieved_chunks=retrieved_chunks or [],
                reranked_chunks=reranked_chunks or [],
                latency_ms=latency_ms or {},
            )
            trace_id = trace_db.id
            if enqueue_metrics and settings.ragas_enabled and settings.chat_metrics_async:
                repo.create_pending_metrics(assistant_msg.id)
                queue.enqueue(
                    "eval_worker.tasks.compute_chat_metrics",
                    str(assistant_msg.id),
                )
                metrics_status = "pending"

        db.commit()
        return sid, assistant_msg.id, trace_id, metrics_status


def _run_guardrails(
    *,
    settings: Settings,
    config_id: uuid.UUID,
    text: str,
    phase: str,
    query: str,
    response: str | None = None,
    chat_message_id: uuid.UUID | None = None,
    span=None,
) -> tuple[bool, str | None, dict]:
    """
    Run guardrails validation for a given phase (input/output).
    Returns (is_blocked, blocking_guard, guard_results).
    Also records a trace to the DB and sets OTEL span attributes.
    """
    from rag_shared.tracing import set_span_attr

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        cfg = repo.get_config(config_id)
        if not cfg:
            return False, None, {}

        # Check if this phase should be validated
        if cfg.mode == "input" and phase != "input":
            return False, None, {}
        if cfg.mode == "output" and phase != "output":
            return False, None, {}

        results = run_guardrails_check(
            text,
            cfg.guards,
            settings.guardrails_url,
            settings.guardrails_timeout_s,
            settings=getattr(cfg, "settings", None) or {},
        )
        is_blocked, blocking_guard = check_blocked(results)

        repo.record_trace(
            config_id=config_id,
            query=query,
            response=response,
            chat_message_id=chat_message_id,
            blocked=is_blocked,
            blocked_by_guard=blocking_guard,
            blocked_on=phase if is_blocked else None,
            guard_results=results,
        )
        db.commit()

    if span:
        set_span_attr(span, "guardrails.config_id", str(config_id))
        set_span_attr(span, f"guardrails.{phase}.blocked", is_blocked)
        if blocking_guard:
            set_span_attr(span, f"guardrails.{phase}.blocked_by", blocking_guard)

    return is_blocked, blocking_guard, results


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    from rag_shared.tracing import rag_pipeline_span, set_span_attr

    settings = request.app.state.settings
    pipeline = request.app.state.pipeline
    queue = request.app.state.queue

    config, source_type, source_id = pipeline.from_request(body)
    generation_model = body.generation_model or settings.chat_model

    with rag_pipeline_span(
        "rag.chat",
        session_id=str(body.session_id) if body.session_id else None,
        query=body.query,
        observation_type="generation",
        model=generation_model,
        metadata={
            "retrieval_mode": config.retrieval_mode.value,
            "rerank_enabled": config.rerank_enabled,
        },
    ) as span:
        # ── Guardrails: input validation ─────────────────────────
        if body.guardrails_config_id:
            blocked, guard, _ = _run_guardrails(
                settings=settings,
                config_id=body.guardrails_config_id,
                text=body.query,
                phase="input",
                query=body.query,
                span=span,
            )
            if blocked:
                answer = _blocked_answer(guard, "input")
                session_id, message_id, trace_id, metrics_status = _persist_chat_turn(
                    settings=settings,
                    queue=queue,
                    session_id=body.session_id,
                    source_type=source_type,
                    source_id=source_id,
                    query=body.query,
                    answer=answer,
                    retrieval_mode=config.retrieval_mode.value,
                    retrieve_limit=config.retrieve_limit,
                    rerank_enabled=config.rerank_enabled,
                    rerank_model=body.rerank_model or settings.reranker_model,
                    generation_model=generation_model,
                    save_trace=True,
                    enqueue_metrics=False,
                    latency_ms=_blocked_latency(guard, "input"),
                )
                set_span_attr(span, "langfuse.trace.output", answer)
                set_span_attr(span, "langfuse.observation.output", answer)
                set_span_attr(span, "output.value", answer)
                set_span_attr(span, "langfuse.session.id", str(session_id))
                set_span_attr(span, "langfuse.observation.metadata.message_id", str(message_id))
                return ChatResponse(
                    message_id=message_id,
                    session_id=session_id,
                    answer=answer,
                    sources=[],
                    trace_id=trace_id,
                    metrics_status=metrics_status,
                )

        result = pipeline.chat(
            body.query,
            config=config,
            source_type=source_type,
            source_id=source_id,
        )

        # ── Guardrails: output validation ────────────────────────
        answer = result.answer
        latency_ms = dict(result.latency_ms or {})
        if body.guardrails_config_id:
            blocked, guard, _ = _run_guardrails(
                settings=settings,
                config_id=body.guardrails_config_id,
                text=answer,
                phase="output",
                query=body.query,
                response=answer,
                span=span,
            )
            if blocked:
                answer = _blocked_answer(guard, "output")
                latency_ms.update(_blocked_latency(guard, "output"))

        set_span_attr(span, "langfuse.trace.output", answer)
        set_span_attr(span, "langfuse.observation.output", answer)
        set_span_attr(span, "output.value", answer)
        set_span_attr(span, "rag.chunks_used", len(result.reranked_chunks))
        for key, val in latency_ms.items():
            if val is not None and not isinstance(val, (list, dict)):
                set_span_attr(span, f"latency.{key}", val)

        session_id, message_id, trace_id, metrics_status = _persist_chat_turn(
            settings=settings,
            queue=queue,
            session_id=body.session_id,
            source_type=source_type,
            source_id=source_id,
            query=body.query,
            answer=answer,
            retrieval_mode=config.retrieval_mode.value,
            retrieve_limit=config.retrieve_limit,
            rerank_enabled=config.rerank_enabled,
            rerank_model=body.rerank_model or settings.reranker_model,
            generation_model=generation_model,
            retrieved_chunks=[c.model_dump() for c in result.retrieved_chunks],
            reranked_chunks=[c.model_dump() for c in result.reranked_chunks],
            latency_ms=latency_ms,
        )

        set_span_attr(span, "langfuse.session.id", str(session_id))
        set_span_attr(span, "langfuse.observation.metadata.message_id", str(message_id))

    sources = [
        SourceCitation(
            source_locator=c.source_locator,
            chunk_index=c.chunk_index,
            rerank_score=c.rerank_score,
        )
        for c in result.reranked_chunks
    ]

    return ChatResponse(
        message_id=message_id,
        session_id=session_id,
        answer=answer,
        sources=sources,
        trace_id=trace_id,
        metrics_status=metrics_status,
    )


@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatRequest):
    """
    SSE streaming endpoint for chat.
    Performs intelligent routing (greeting vs RAG) and streams status/token events.
    """
    import asyncio
    import json
    import queue
    import time

    from fastapi.responses import StreamingResponse
    from opentelemetry import context as otel_context
    from rag_core.query_router import QueryRoute, RouteResult, classify_query
    from rag_shared.tracing import rag_pipeline_span, set_span_attr

    settings = request.app.state.settings
    pipeline = request.app.state.pipeline
    job_queue = request.app.state.queue

    config, source_type, source_id = pipeline.from_request(body)
    generation_model = body.generation_model or settings.chat_model

    # Capture request context so the worker thread nests under the same trace.
    # iterate_in_threadpool resumes the generator across pool threads, which
    # breaks OTEL ContextVar attach/detach tokens — run the whole sync body in
    # one worker thread and bridge chunks via a queue instead.
    parent_otel_ctx = otel_context.get_current()
    chunk_queue: queue.Queue[str | None] = queue.Queue()

    def _emit(chunk: str) -> None:
        chunk_queue.put(chunk)

    def _run_stream() -> None:
        token = otel_context.attach(parent_otel_ctx)
        try:
            # ── Guardrails: input validation (stream) ────────────
            if body.guardrails_config_id:
                _emit(f'data: {json.dumps({"type": "status", "message": "Checking guardrails..."})}\n\n')
                blocked, guard, _ = _run_guardrails(
                    settings=settings,
                    config_id=body.guardrails_config_id,
                    text=body.query,
                    phase="input",
                    query=body.query,
                )
                if blocked:
                    answer = _blocked_answer(guard, "input")
                    sid, msg_id, _, _ = _persist_chat_turn(
                        settings=settings,
                        queue=job_queue,
                        session_id=body.session_id,
                        source_type=source_type,
                        source_id=source_id,
                        query=body.query,
                        answer=answer,
                        retrieval_mode=config.retrieval_mode.value,
                        retrieve_limit=config.retrieve_limit,
                        rerank_enabled=config.rerank_enabled,
                        rerank_model=body.rerank_model or settings.reranker_model,
                        generation_model=generation_model,
                        save_trace=True,
                        enqueue_metrics=False,
                        latency_ms=_blocked_latency(guard, "input"),
                    )
                    _emit(f"data: {json.dumps(_blocked_payload(content=answer, guard=guard, phase='input', session_id=sid, message_id=msg_id))}\n\n")
                    _emit(
                        f'data: {json.dumps({"type": "session", "session_id": str(sid), "message_id": str(msg_id), "route": "blocked", "metrics_status": "skipped"})}\n\n'
                    )
                    return

            # Honor per-request UI toggle; do NOT use global settings.router_enabled alone
            router_on = bool(getattr(body, "router_enabled", False))
            router_mode = getattr(body, "router_mode", None)
            if router_on:
                route_res = classify_query(
                    body.query,
                    settings,
                    router_enabled=True,
                    router_mode=router_mode,
                )
            else:
                # Manual mode: never greet; follow rag_mode only
                route_res = RouteResult(route=QueryRoute.SIMPLE_RAG)

            if route_res.route == QueryRoute.GREETING:
                with rag_pipeline_span(
                    "rag.chat.stream",
                    session_id=str(body.session_id) if body.session_id else None,
                    query=body.query,
                    observation_type="generation",
                    model=generation_model,
                    metadata={"route": "greeting"},
                ) as span:
                    _emit(f'data: {json.dumps({"type": "status", "message": "Processing message"})}\n\n')
                    answer = route_res.greeting_response or "Hello!"
                    for char in answer:
                        _emit(f'data: {json.dumps({"type": "token", "content": char})}\n\n')
                        time.sleep(0.01)

                    set_span_attr(span, "langfuse.trace.output", answer)
                    set_span_attr(span, "langfuse.observation.output", answer)
                    set_span_attr(span, "output.value", answer)
                    set_span_attr(span, "rag.chunks_used", 0)

                    sid, msg_id, _, _ = _persist_chat_turn(
                        settings=settings,
                        queue=job_queue,
                        session_id=body.session_id,
                        source_type=source_type,
                        source_id=source_id,
                        query=body.query,
                        answer=answer,
                        retrieval_mode=config.retrieval_mode.value,
                        retrieve_limit=config.retrieve_limit,
                        rerank_enabled=config.rerank_enabled,
                        rerank_model=body.rerank_model or settings.reranker_model,
                        generation_model=generation_model,
                        save_trace=False,
                        enqueue_metrics=False,
                    )
                    set_span_attr(span, "langfuse.session.id", str(sid))
                    set_span_attr(span, "langfuse.observation.metadata.message_id", str(msg_id))

                _emit(
                    f'data: {json.dumps({"type": "done", "metadata": {"sources": [], "route": "greeting", "session_id": str(sid), "message_id": str(msg_id)}})}\n\n'
                )
                _emit(
                    f'data: {json.dumps({"type": "session", "session_id": str(sid), "message_id": str(msg_id), "route": "greeting"})}\n\n'
                )
                return

            if router_on:
                use_crag = route_res.route == QueryRoute.CRAG
                effective_route = "self_corrective_auto" if use_crag else "simple_rag_auto"
            else:
                use_crag = config.rag_mode == "self_corrective"
                effective_route = "self_corrective" if use_crag else "normal"

            # Span must wrap retrieve/rerank/generate so httpx child spans nest correctly
            # (same shape as /chat). Creating it after the stream left Langfuse with empty traces.
            out_blocked = False
            out_guard: str | None = None
            with rag_pipeline_span(
                "rag.chat.stream",
                session_id=str(body.session_id) if body.session_id else None,
                query=body.query,
                observation_type="generation",
                model=generation_model,
                metadata={
                    "retrieval_mode": config.retrieval_mode.value,
                    "rerank_enabled": config.rerank_enabled,
                    "route": effective_route,
                },
            ) as span:
                if use_crag:
                    gen = pipeline.stream_chat_self_corrective(
                        body.query, config=config, source_type=source_type, source_id=source_id
                    )
                else:
                    gen = pipeline.stream_chat(
                        body.query, config=config, source_type=source_type, source_id=source_id
                    )

                final_metadata: dict = {}
                for event in gen:
                    if event.type == "done":
                        final_metadata = event.metadata or {}

                    payload = {"type": event.type}
                    if event.message:
                        payload["message"] = event.message
                    if event.content:
                        payload["content"] = event.content
                    if event.metadata:
                        payload["metadata"] = event.metadata
                    _emit(f"data: {json.dumps(payload)}\n\n")

                if "answer" not in final_metadata:
                    set_span_attr(span, "error", True)
                    set_span_attr(span, "langfuse.observation.status_message", "stream ended without answer")
                    return

                answer = final_metadata["answer"]
                retrieved_chunks = final_metadata.get("retrieved_chunks", [])
                reranked_chunks = final_metadata.get("reranked_chunks", [])
                latency_ms = dict(final_metadata.get("latency_ms") or {})
                latency_ms["route"] = effective_route
                out_blocked = False
                out_guard: str | None = None

                # ── Guardrails: output validation (stream) ───────
                if body.guardrails_config_id:
                    out_blocked, out_guard, _ = _run_guardrails(
                        settings=settings,
                        config_id=body.guardrails_config_id,
                        text=answer,
                        phase="output",
                        query=body.query,
                        response=answer,
                        span=span,
                    )
                    if out_blocked:
                        answer = _blocked_answer(out_guard, "output")
                        latency_ms.update(_blocked_latency(out_guard, "output"))

                set_span_attr(span, "langfuse.trace.output", answer)
                set_span_attr(span, "langfuse.observation.output", answer)
                set_span_attr(span, "output.value", answer)
                set_span_attr(span, "rag.chunks_used", len(reranked_chunks))
                for key, val in latency_ms.items():
                    if val is not None and not isinstance(val, (list, dict)):
                        set_span_attr(span, f"latency.{key}", val)

                sid, msg_id, _, metrics_status = _persist_chat_turn(
                    settings=settings,
                    queue=job_queue,
                    session_id=body.session_id,
                    source_type=source_type,
                    source_id=source_id,
                    query=body.query,
                    answer=answer,
                    retrieval_mode=config.retrieval_mode.value,
                    retrieve_limit=config.retrieve_limit,
                    rerank_enabled=config.rerank_enabled,
                    rerank_model=body.rerank_model or settings.reranker_model,
                    generation_model=generation_model,
                    retrieved_chunks=retrieved_chunks,
                    reranked_chunks=reranked_chunks,
                    latency_ms=latency_ms or {},
                    enqueue_metrics=not out_blocked,
                )
                set_span_attr(span, "langfuse.session.id", str(sid))
                set_span_attr(span, "langfuse.observation.metadata.message_id", str(msg_id))

            if out_blocked:
                _emit(f"data: {json.dumps(_blocked_payload(content=answer, guard=out_guard, phase='output', session_id=sid, message_id=msg_id))}\n\n")
            _emit(
                f'data: {json.dumps({"type": "session", "session_id": str(sid), "message_id": str(msg_id), "route": "blocked" if out_blocked else effective_route, "metrics_status": "skipped" if out_blocked else metrics_status})}\n\n'
            )

        except Exception as e:
            logger.exception("Chat stream failed")
            _emit(f'data: {json.dumps({"type": "error", "content": str(e)})}\n\n')
        finally:
            try:
                otel_context.detach(token)
            except ValueError:
                # Defensive: should not happen when the worker owns the full stack.
                logger.debug("otel_detach_skipped token_from_different_context", exc_info=True)
            chunk_queue.put(None)

    async def async_event_generator():
        loop = asyncio.get_running_loop()
        worker = loop.run_in_executor(None, _run_stream)
        try:
            while True:
                item = await loop.run_in_executor(None, chunk_queue.get)
                if item is None:
                    break
                yield item
        finally:
            await worker

    return StreamingResponse(
        async_event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/messages/{message_id}/metrics", response_model=MetricsResponse)
def get_message_metrics(message_id: uuid.UUID, request: Request) -> MetricsResponse:
    settings = request.app.state.settings
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        metrics = repo.get_metrics(message_id)
        if not metrics:
            raise HTTPException(status_code=404, detail="Metrics not found")
        return _build_metrics_response(message_id, metrics)


def _build_chat_stat_item(metrics, message, trace) -> ChatStatItem:
    raw = metrics.raw_ragas if isinstance(metrics.raw_ragas, dict) else None
    staged = _staged_metrics(raw)
    return ChatStatItem(
        message_id=message.id,
        session_id=message.session_id,
        query=trace.query if trace else None,
        answer=message.content,
        faithfulness=metrics.faithfulness,
        answer_relevancy=metrics.answer_relevancy,
        context_precision=metrics.context_precision,
        context_recall=metrics.context_recall,
        kendall_tau=_reranker_metric(raw, "kendall_tau"),
        mrr=_reranker_metric(raw, "mrr"),
        ndcg=_reranker_metric(raw, "ndcg"),
        metrics=staged,
        metrics_status=metrics.status,
        computed_at=metrics.computed_at.isoformat() if metrics.computed_at else None,
        latency_ms=trace.latency_ms if trace else None,
        retrieval_mode=trace.retrieval_mode if trace else None,
        rerank_enabled=trace.rerank_enabled if trace else None,
        generation_model=trace.generation_model if trace else None,
        created_at=message.created_at.isoformat() if message.created_at else None,
    )


@router.get("/chat/stats", response_model=ChatStatsResponse)
def get_chat_stats(
    limit: int = 20,
    settings: Settings = Depends(get_settings),
) -> ChatStatsResponse:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        rows = repo.list_recent_metrics_stats(limit=limit)
        items = [
            _build_chat_stat_item(metrics, message, trace)
            for metrics, message, trace in rows
        ]

    return ChatStatsResponse(limit=limit, count=len(items), items=items)


@router.get("/chat/sessions", response_model=ChatSessionsResponse)
def list_chat_sessions(
    limit: int = 50,
    settings: Settings = Depends(get_settings),
) -> ChatSessionsResponse:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        rows = repo.list_sessions(limit=limit)
        items = [
            ChatSessionItem(
                session_id=session.id,
                created_at=session.created_at.isoformat() if session.created_at else None,
                last_message_at=last_message_at.isoformat() if last_message_at else None,
                preview=preview,
                message_count=message_count,
            )
            for session, message_count, last_message_at, preview in rows
        ]

    return ChatSessionsResponse(limit=limit, count=len(items), items=items)


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatSessionMessagesResponse)
def get_chat_session_messages(
    session_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> ChatSessionMessagesResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        if not repo.get_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")

        rows = repo.list_session_messages(session_id)
        items = []
        for message, trace, metrics in rows:
            latency = (trace.latency_ms or {}) if trace else {}
            blocked = bool(latency.get("blocked") or latency.get("route") == "blocked")
            items.append(
                ChatMessageItem(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at.isoformat() if message.created_at else None,
                    trace=MessageTraceInfo(
                        retrieval_mode=trace.retrieval_mode,
                        rerank_enabled=trace.rerank_enabled,
                        generation_model=trace.generation_model,
                        route=latency.get("route"),
                    )
                    if trace
                    else None,
                    sources=_sources_from_trace(trace) if message.role == "assistant" else [],
                    metrics_status=metrics.status if metrics else None,
                    blocked=blocked,
                    blocked_by_guard=latency.get("blocked_by_guard"),
                    blocked_on=latency.get("blocked_on"),
                )
            )

    return ChatSessionMessagesResponse(session_id=session_id, count=len(items), items=items)


@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_chat_session(
    session_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> None:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        if not repo.soft_delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        db.commit()


@router.delete("/chat/messages/{message_id}", response_model=DeleteMessageResponse)
def delete_chat_message(
    message_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> DeleteMessageResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        message = repo.get_message(message_id)
        if message is None or message.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Message not found")
        session_id = message.session_id
        deleted_ids = repo.soft_delete_message_turn(message_id)
        if deleted_ids is None:
            raise HTTPException(status_code=404, detail="Message not found")
        db.commit()
        return DeleteMessageResponse(session_id=session_id, deleted_message_ids=deleted_ids)
