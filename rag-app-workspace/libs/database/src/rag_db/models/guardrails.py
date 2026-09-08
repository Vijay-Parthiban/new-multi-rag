from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_db.models.base import Base


class GuardrailsConfig(Base):
    __tablename__ = "guardrails_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    guards: Mapped[list] = mapped_column(JSONB, default=list)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    mode: Mapped[str] = mapped_column(String, default="both")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    traces: Mapped[list["GuardrailsTrace"]] = relationship(back_populates="config")


class GuardrailsTrace(Base):
    __tablename__ = "guardrails_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guardrails_configs.id", ondelete="SET NULL"), nullable=True)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_by_guard: Mapped[str | None] = mapped_column(String, nullable=True)
    blocked_on: Mapped[str | None] = mapped_column(String, nullable=True)
    guard_results: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    config: Mapped["GuardrailsConfig | None"] = relationship(back_populates="traces")


class GuardrailsGoldenDataset(Base):
    __tablename__ = "guardrails_golden_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["GuardrailsGoldenDatasetItem"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    runs: Mapped[list["GuardrailsEvalRun"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class GuardrailsGoldenDatasetItem(Base):
    __tablename__ = "guardrails_golden_dataset_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guardrails_golden_datasets.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(String, default="input")
    expected_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_guard: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["GuardrailsGoldenDataset"] = relationship(back_populates="items")


class GuardrailsEvalRun(Base):
    __tablename__ = "guardrails_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guardrails_golden_datasets.id", ondelete="CASCADE"), nullable=False)
    config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guardrails_configs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    aggregate_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset: Mapped["GuardrailsGoldenDataset"] = relationship(back_populates="runs")
    items: Mapped[list["GuardrailsEvalRunItem"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class GuardrailsEvalRunItem(Base):
    __tablename__ = "guardrails_eval_run_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guardrails_eval_runs.id", ondelete="CASCADE"), nullable=False)
    dataset_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String, default="completed")
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_guard: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_guard: Mapped[str | None] = mapped_column(String, nullable=True)
    correct_block: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    correct_guard: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    guard_results: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["GuardrailsEvalRun"] = relationship(back_populates="items")
