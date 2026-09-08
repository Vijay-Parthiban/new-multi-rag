from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_db.models.base import Base


class GoldenDataset(Base):
    __tablename__ = "golden_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["GoldenDatasetItem"]] = relationship(back_populates="dataset")
    runs: Mapped[list["EvaluationRun"]] = relationship(back_populates="dataset")


class GoldenDatasetItem(Base):
    __tablename__ = "golden_dataset_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("golden_datasets.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_sources: Mapped[list] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["GoldenDataset"] = relationship(back_populates="items")
    run_items: Mapped[list["EvaluationRunItem"]] = relationship(back_populates="dataset_item")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("golden_datasets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    aggregate_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["GoldenDataset"] = relationship(back_populates="runs")
    items: Mapped[list["EvaluationRunItem"]] = relationship(back_populates="run")


class EvaluationRunItem(Base):
    __tablename__ = "evaluation_run_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    dataset_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("golden_dataset_items.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, default="pending")
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    retrieval_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reranked_chunks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rerank_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["EvaluationRun"] = relationship(back_populates="items")
    dataset_item: Mapped["GoldenDatasetItem"] = relationship(back_populates="run_items")
