from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from rag_core import PipelineRequest
from rag_db.models.chat import ChatPipelineTrace
from rag_db.repositories.chat_repository import ChatRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings

router = APIRouter(tags=["chat"])


class ChatRequest(PipelineRequest):
    session_id: uuid.UUID | None = None


class SourceCitation(BaseModel):
    source_locator: str
    chunk_index: int
    rerank_score: float


class ChatResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    answer: str
    sources: list[SourceCitation]
    trace_id: uuid.UUID
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


class ChatMessageItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: str | None = None
    trace: MessageTraceInfo | None = None
    sources: list[SourceCitation] = []
    metrics_status: str | None = None


class ChatSessionMessagesResponse(BaseModel):
    session_id: uuid.UUID
    count: int
    items: list[ChatMessageItem]


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
        result = pipeline.chat(
            body.query,
            config=config,
            source_type=source_type,
            source_id=source_id,
        )
        set_span_attr(span, "langfuse.trace.output", result.answer)
        set_span_attr(span, "langfuse.observation.output", result.answer)
        set_span_attr(span, "output.value", result.answer)
        set_span_attr(span, "rag.chunks_used", len(result.reranked_chunks))
        for key, val in (result.latency_ms or {}).items():
            if val is not None:
                set_span_attr(span, f"latency.{key}", val)

        session_factory = get_session_factory(settings)
        with session_factory() as db:
            repo = ChatRepository(db)
            if body.session_id:
                session_id = body.session_id
            else:
                session = repo.create_session(
                    source_type=source_type,
                    source_id=source_id,
                )
                session_id = session.id

            repo.add_message(session_id, "user", body.query)
            assistant_msg = repo.add_message(session_id, "assistant", result.answer)
            trace_db = repo.save_pipeline_trace(
                assistant_msg.id,
                query=body.query,
                retrieval_mode=config.retrieval_mode.value,
                retrieve_limit=config.retrieve_limit,
                rerank_enabled=config.rerank_enabled,
                rerank_model=body.rerank_model or settings.reranker_model,
                generation_model=generation_model,
                retrieved_chunks=[c.model_dump() for c in result.retrieved_chunks],
                reranked_chunks=[c.model_dump() for c in result.reranked_chunks],
                latency_ms=result.latency_ms,
            )
            metrics_status = "skipped"
            if settings.ragas_enabled and settings.chat_metrics_async:
                repo.create_pending_metrics(assistant_msg.id)
                queue.enqueue(
                    "eval_worker.tasks.compute_chat_metrics",
                    str(assistant_msg.id),
                )
                metrics_status = "pending"

            message_id = assistant_msg.id
            trace_id = trace_db.id
            db.commit()

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
        answer=result.answer,
        sources=sources,
        trace_id=trace_id,
        metrics_status=metrics_status,
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
        items = [
            ChatMessageItem(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at.isoformat() if message.created_at else None,
                trace=MessageTraceInfo(
                    retrieval_mode=trace.retrieval_mode,
                    rerank_enabled=trace.rerank_enabled,
                    generation_model=trace.generation_model,
                )
                if trace
                else None,
                sources=_sources_from_trace(trace) if message.role == "assistant" else [],
                metrics_status=metrics.status if metrics else None,
            )
            for message, trace, metrics in rows
        ]

    return ChatSessionMessagesResponse(session_id=session_id, count=len(items), items=items)
