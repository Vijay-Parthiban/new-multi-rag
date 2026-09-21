from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_db.models.guardrails import (
    GuardrailsEvalRun,
    GuardrailsEvalRunItem,
    GuardrailsGoldenDataset,
    GuardrailsGoldenDatasetItem,
)


class GuardrailsEvaluationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def import_dataset(
        self,
        name: str,
        description: str | None = None,
        items: list[dict[str, Any]] | None = None,
        replace: bool = True,
    ) -> GuardrailsGoldenDataset:
        # A dataset name is unique. `replace` decides whether an existing dataset with the
        # same name is overwritten or reported as a conflict.
        existing = self._session.scalars(
            select(GuardrailsGoldenDataset).where(GuardrailsGoldenDataset.name == name)
        ).first()
        if existing:
            if not replace:
                raise ValueError(f"A dataset named '{name}' already exists")
            self._session.delete(existing)
            self._session.flush()

        dataset = GuardrailsGoldenDataset(name=name, description=description)
        self._session.add(dataset)
        self._session.flush()

        if items:
            for item in items:
                ds_item = GuardrailsGoldenDatasetItem(
                    dataset_id=dataset.id,
                    text=item.get("text", ""),
                    phase=item.get("phase", "input"),
                    expected_blocked=item.get("expected_blocked", False),
                    expected_guard=item.get("expected_guard"),
                    category=item.get("category"),
                    metadata_=item.get("metadata", {}),
                )
                self._session.add(ds_item)
            self._session.flush()

        return dataset

    def list_datasets(self) -> list[GuardrailsGoldenDataset]:
        stmt = select(GuardrailsGoldenDataset).order_by(GuardrailsGoldenDataset.created_at.desc())
        return list(self._session.scalars(stmt).all())

    def get_dataset(self, dataset_id: uuid.UUID) -> GuardrailsGoldenDataset | None:
        return self._session.get(GuardrailsGoldenDataset, dataset_id)

    def delete_dataset(self, dataset_id: uuid.UUID) -> bool:
        ds = self.get_dataset(dataset_id)
        if not ds:
            return False
        self._session.delete(ds)
        self._session.flush()
        return True

    def list_dataset_items(self, dataset_id: uuid.UUID) -> list[GuardrailsGoldenDatasetItem]:
        stmt = (
            select(GuardrailsGoldenDatasetItem)
            .where(GuardrailsGoldenDatasetItem.dataset_id == dataset_id)
            .order_by(GuardrailsGoldenDatasetItem.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def create_run(
        self,
        dataset_id: uuid.UUID,
        config_id: uuid.UUID,
        config_snapshot: dict[str, Any] | None = None,
    ) -> GuardrailsEvalRun:
        run = GuardrailsEvalRun(
            dataset_id=dataset_id,
            config_id=config_id,
            config_snapshot=config_snapshot,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def save_run_item(
        self,
        run_id: uuid.UUID,
        dataset_item_id: uuid.UUID,
        status: str = "completed",
        skipped: bool = False,
        skip_reason: str | None = None,
        expected_blocked: bool = False,
        expected_guard: str | None = None,
        actual_blocked: bool = False,
        actual_guard: str | None = None,
        correct_block: bool | None = None,
        correct_guard: bool | None = None,
        guard_results: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> GuardrailsEvalRunItem:
        run_item = GuardrailsEvalRunItem(
            run_id=run_id,
            dataset_item_id=dataset_item_id,
            status=status,
            skipped=skipped,
            skip_reason=skip_reason,
            expected_blocked=expected_blocked,
            expected_guard=expected_guard,
            actual_blocked=actual_blocked,
            actual_guard=actual_guard,
            correct_block=correct_block,
            correct_guard=correct_guard,
            guard_results=guard_results or {},
            error_message=error_message,
        )
        self._session.add(run_item)
        self._session.flush()
        return run_item

    def complete_run(
        self,
        run_id: uuid.UUID,
        aggregate_metrics: dict[str, Any] | None = None,
        status: str = "completed",
        error_message: str | None = None,
    ) -> GuardrailsEvalRun | None:
        run = self._session.get(GuardrailsEvalRun, run_id)
        if not run:
            return None
        run.status = status
        run.aggregate_metrics = aggregate_metrics
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        self._session.flush()
        return run

    def get_run(self, run_id: uuid.UUID) -> GuardrailsEvalRun | None:
        return self._session.get(GuardrailsEvalRun, run_id)

    def list_runs_for_dataset(
        self, dataset_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> tuple[list[GuardrailsEvalRun], int]:
        stmt = select(GuardrailsEvalRun).where(GuardrailsGoldenDataset.id == dataset_id)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self._session.scalar(count_stmt) or 0

        stmt = stmt.order_by(GuardrailsEvalRun.created_at.desc()).offset(skip).limit(limit)
        runs = list(self._session.scalars(stmt).all())
        return runs, total

    def list_run_items(self, run_id: uuid.UUID) -> list[GuardrailsEvalRunItem]:
        """Every scored row of one run.

        All rows of a run are inserted in a single transaction, so `created_at` is the same
        for each. Ordering by id as well keeps the order stable between calls.
        """
        stmt = (
            select(GuardrailsEvalRunItem)
            .where(GuardrailsEvalRunItem.run_id == run_id)
            .order_by(GuardrailsEvalRunItem.created_at.asc(), GuardrailsEvalRunItem.id.asc())
        )
        return list(self._session.scalars(stmt).all())
