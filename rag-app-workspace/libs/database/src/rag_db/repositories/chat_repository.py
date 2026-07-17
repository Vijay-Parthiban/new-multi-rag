from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from rag_db.models.chat import ChatMessage, ChatMessageMetrics, ChatPipelineTrace, ChatSession
from rag_db.sanitize import strip_null_bytes


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_session(
        self,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> ChatSession:
        session = ChatSession(
            source_type=source_type,
            source_id=source_id,
            metadata_=strip_null_bytes(metadata or {}),
        )
        self._session.add(session)
        self._session.flush()
        return session

    def add_message(self, session_id: uuid.UUID, role: str, content: str) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=strip_null_bytes(content),
        )
        self._session.add(message)
        self._session.flush()
        return message

    def save_pipeline_trace(
        self,
        chat_message_id: uuid.UUID,
        *,
        query: str,
        retrieval_mode: str,
        retrieve_limit: int,
        rerank_enabled: bool,
        rerank_model: str | None,
        generation_model: str | None,
        retrieved_chunks: list,
        reranked_chunks: list,
        latency_ms: dict,
    ) -> ChatPipelineTrace:
        trace = ChatPipelineTrace(
            chat_message_id=chat_message_id,
            query=strip_null_bytes(query),
            retrieval_mode=retrieval_mode,
            retrieve_limit=retrieve_limit,
            rerank_enabled=rerank_enabled,
            rerank_model=rerank_model,
            generation_model=generation_model,
            retrieved_chunks=strip_null_bytes(retrieved_chunks),
            reranked_chunks=strip_null_bytes(reranked_chunks),
            latency_ms=strip_null_bytes(latency_ms),
        )
        self._session.add(trace)
        self._session.flush()
        return trace

    def create_pending_metrics(self, chat_message_id: uuid.UUID) -> ChatMessageMetrics:
        metrics = ChatMessageMetrics(chat_message_id=chat_message_id, status="pending")
        self._session.add(metrics)
        self._session.flush()
        return metrics

    def get_message(self, message_id: uuid.UUID) -> ChatMessage | None:
        return self._session.get(ChatMessage, message_id)

    def get_metrics(self, message_id: uuid.UUID) -> ChatMessageMetrics | None:
        return (
            self._session.query(ChatMessageMetrics)
            .filter(ChatMessageMetrics.chat_message_id == message_id)
            .one_or_none()
        )

    def update_metrics(
        self,
        message_id: uuid.UUID,
        *,
        scores: dict,
        status: str = "completed",
        error_message: str | None = None,
    ) -> ChatMessageMetrics | None:
        metrics = self.get_metrics(message_id)
        if not metrics:
            return None
        metrics.faithfulness = scores.get("faithfulness")
        metrics.answer_relevancy = scores.get("answer_relevancy")
        metrics.context_precision = scores.get("context_precision")
        metrics.context_recall = scores.get("context_recall")
        metrics.raw_ragas = strip_null_bytes(scores.get("raw_ragas") or scores)
        metrics.status = status
        metrics.error_message = strip_null_bytes(error_message) if error_message else None
        metrics.computed_at = datetime.now(timezone.utc)
        self._session.flush()
        return metrics

    def get_trace_for_message(self, message_id: uuid.UUID) -> ChatPipelineTrace | None:
        return (
            self._session.query(ChatPipelineTrace)
            .filter(ChatPipelineTrace.chat_message_id == message_id)
            .one_or_none()
        )

    def get_session(self, session_id: uuid.UUID) -> ChatSession | None:
        return self._session.get(ChatSession, session_id)

    def list_sessions(
        self, limit: int = 50
    ) -> list[tuple[ChatSession, int, datetime | None, str | None]]:
        from sqlalchemy import func

        rows = (
            self._session.query(
                ChatSession,
                func.count(ChatMessage.id).label("message_count"),
                func.max(ChatMessage.created_at).label("last_message_at"),
            )
            .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .group_by(ChatSession.id)
            .order_by(func.max(ChatMessage.created_at).desc())
            .limit(limit)
            .all()
        )

        if not rows:
            return []

        session_ids = [session.id for session, _, _ in rows]
        previews: dict[uuid.UUID, str] = {}
        for msg in (
            self._session.query(ChatMessage)
            .filter(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "user")
            .order_by(ChatMessage.session_id, ChatMessage.created_at.asc())
            .all()
        ):
            if msg.session_id not in previews:
                previews[msg.session_id] = msg.content[:120]

        return [
            (session, message_count, last_message_at, previews.get(session.id))
            for session, message_count, last_message_at in rows
        ]

    def list_session_messages(
        self, session_id: uuid.UUID
    ) -> list[tuple[ChatMessage, ChatPipelineTrace | None, ChatMessageMetrics | None]]:
        return (
            self._session.query(ChatMessage, ChatPipelineTrace, ChatMessageMetrics)
            .outerjoin(ChatPipelineTrace, ChatPipelineTrace.chat_message_id == ChatMessage.id)
            .outerjoin(ChatMessageMetrics, ChatMessageMetrics.chat_message_id == ChatMessage.id)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    def list_recent_metrics_stats(self, limit: int = 20) -> list[tuple[ChatMessageMetrics, ChatMessage, ChatPipelineTrace | None]]:
        return (
            self._session.query(ChatMessageMetrics, ChatMessage, ChatPipelineTrace)
            .join(ChatMessage, ChatMessageMetrics.chat_message_id == ChatMessage.id)
            .outerjoin(ChatPipelineTrace, ChatPipelineTrace.chat_message_id == ChatMessage.id)
            .filter(ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
