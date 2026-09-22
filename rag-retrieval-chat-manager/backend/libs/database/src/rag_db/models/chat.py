from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_db.models.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
    trace: Mapped["ChatPipelineTrace | None"] = relationship(back_populates="message", uselist=False)
    metrics: Mapped["ChatMessageMetrics | None"] = relationship(back_populates="message", uselist=False)


class ChatPipelineTrace(Base):
    __tablename__ = "chat_pipeline_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_messages.id"), unique=True, nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_mode: Mapped[str] = mapped_column(String, nullable=False)
    retrieve_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    rerank_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rerank_model: Mapped[str | None] = mapped_column(String, nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieved_chunks: Mapped[list] = mapped_column(JSONB, default=list)
    reranked_chunks: Mapped[list] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[dict] = mapped_column(JSONB, default=dict)
    # "test" for a turn from the Chat page, "prod" for the callable endpoint. Set from the
    # request header, and anything without it is prod. The Real Time Monitoring page tags
    # each log with this.
    trace_mode: Mapped[str] = mapped_column(String, nullable=False, server_default="prod")
    # The OTEL ids of the turn span, as hex. The metrics worker parents its own span under
    # these, so one question stays one trace instead of producing a second one.
    otel_trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    otel_span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["ChatMessage"] = relationship(back_populates="trace")


class ChatMessageMetrics(Base):
    __tablename__ = "chat_message_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_messages.id"), unique=True, nullable=False
    )
    faithfulness: Mapped[float | None] = mapped_column(nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(nullable=True)
    context_precision: Mapped[float | None] = mapped_column(nullable=True)
    context_recall: Mapped[float | None] = mapped_column(nullable=True)
    raw_ragas: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped["ChatMessage"] = relationship(back_populates="metrics")
