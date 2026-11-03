"""One chat turn, as the OpenTelemetry Collector delivered it.

No chat table stores which pipeline a turn belonged to; the turn span is the only place
that link exists (`rag.pipeline.slug`). The collector posts each turn span to rag-api,
which stores it here so the Dataset Feedback page can list the conversations of one
pipeline. `(trace_id, span_id)` is unique so a collector retry never duplicates a turn.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from rag_db.models.base import Base


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("trace_id", "span_id", name="uq_conversation_turns_span"),
        Index("ix_conversation_turns_slug_session", "pipeline_slug", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    span_id: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_mode: Mapped[str] = mapped_column(String, nullable=False, server_default="prod")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # The chat message of the reply. No foreign key: the chat row may be deleted.
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    chunks_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
