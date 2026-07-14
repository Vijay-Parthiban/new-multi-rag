from __future__ import annotations

import uuid
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy.orm import Session

from rag_db.models.evaluation import (
    EvaluationRun,
    EvaluationRunItem,
    GoldenDataset,
    GoldenDatasetItem,
)


class EvaluationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_dataset(self, dataset_id: uuid.UUID) -> GoldenDataset | None:
        return self._session.get(GoldenDataset, dataset_id)

    def get_dataset_by_name(self, name: str) -> GoldenDataset | None:
        return (
            self._session.query(GoldenDataset)
            .filter(GoldenDataset.name == name)
            .one_or_none()
        )

    def list_datasets(self, limit: int = 50) -> list[GoldenDataset]:
        return (
            self._session.query(GoldenDataset)
            .order_by(GoldenDataset.created_at.desc())
            .limit(limit)
            .all()
        )

    def count_dataset_items(self, dataset_id: uuid.UUID) -> int:
        return (
            self._session.query(GoldenDatasetItem)
            .filter(GoldenDatasetItem.dataset_id == dataset_id)
            .count()
        )

    def delete_dataset(self, dataset_id: uuid.UUID) -> None:
        self._session.query(GoldenDatasetItem).filter(
            GoldenDatasetItem.dataset_id == dataset_id
        ).delete()
        dataset = self.get_dataset(dataset_id)
        if dataset:
            self._session.delete(dataset)
            self._session.flush()

    def import_dataset(
        self,
        *,
        name: str,
        description: str | None,
        items: list[dict],
        replace: bool = False,
    ) -> GoldenDataset:
        existing = self.get_dataset_by_name(name)
        if existing:
            if not replace:
                raise ValueError(f"Dataset '{name}' already exists")
            self.delete_dataset(existing.id)

        dataset = self.create_dataset(name=name, description=description)
        for item in items:
            self.add_dataset_item(
                dataset.id,
                question=item["question"],
                ground_truth_answer=item.get("ground_truth_answer"),
                expected_sources=item.get("expected_sources") or [],
                metadata=item.get("metadata") or {},
            )
        return dataset

    def list_dataset_items(self, dataset_id: uuid.UUID) -> list[GoldenDatasetItem]:
        return (
            self._session.query(GoldenDatasetItem)
            .filter(GoldenDatasetItem.dataset_id == dataset_id)
            .all()
        )

    def create_run(self, dataset_id: uuid.UUID, config: dict) -> EvaluationRun:
        run = EvaluationRun(dataset_id=dataset_id, status="queued", config=config)
        self._session.add(run)
        self._session.flush()
        return run

    def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._session.get(EvaluationRun, run_id)

    def mark_run_running(self, run_id: uuid.UUID) -> None:
        run = self.get_run(run_id)
        if run:
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            self._session.flush()

    def mark_run_completed(self, run_id: uuid.UUID, aggregate_metrics: dict) -> None:
        run = self.get_run(run_id)
        if run:
            run.status = "completed"
            run.aggregate_metrics = aggregate_metrics
            run.completed_at = datetime.now(timezone.utc)
            self._session.flush()

    def mark_run_failed(self, run_id: uuid.UUID, error: str) -> None:
        run = self.get_run(run_id)
        if run:
            run.status = "failed"
            run.aggregate_metrics = {"error": error}
            run.completed_at = datetime.now(timezone.utc)
            self._session.flush()

    def get_run_progress(self, run_id: uuid.UUID) -> dict[str, int]:
        run = self.get_run(run_id)
        if not run:
            return {"items_total": 0, "items_completed": 0, "items_failed": 0}

        items_total = self.count_dataset_items(run.dataset_id)
        rows = (
            self._session.query(EvaluationRunItem.status)
            .filter(EvaluationRunItem.run_id == run_id)
            .all()
        )
        completed = sum(1 for (status,) in rows if status == "completed")
        failed = sum(1 for (status,) in rows if status == "failed")
        return {
            "items_total": items_total,
            "items_completed": completed,
            "items_failed": failed,
        }

    def create_run_item(self, run_id: uuid.UUID, dataset_item_id: uuid.UUID) -> EvaluationRunItem:
        item = EvaluationRunItem(
            run_id=run_id,
            dataset_item_id=dataset_item_id,
            status="pending",
        )
        self._session.add(item)
        self._session.flush()
        return item

    def save_run_item_result(
        self,
        item_id: uuid.UUID,
        *,
        retrieved_chunks: list,
        retrieval_metrics: dict,
        reranked_chunks: list,
        rerank_metrics: dict,
        generated_answer: str,
        generation_metrics: dict,
    ) -> None:
        item = self._session.get(EvaluationRunItem, item_id)
        if not item:
            return
        item.status = "completed"
        item.retrieved_chunks = retrieved_chunks
        item.retrieval_metrics = retrieval_metrics
        item.reranked_chunks = reranked_chunks
        item.rerank_metrics = rerank_metrics
        item.generated_answer = generated_answer
        item.generation_metrics = generation_metrics
        self._session.flush()

    def fail_run_item(self, item_id: uuid.UUID, error: str) -> None:
        item = self._session.get(EvaluationRunItem, item_id)
        if item:
            item.status = "failed"
            item.error_message = error
            self._session.flush()

    def aggregate_run_metrics(self, run_id: uuid.UUID) -> dict:
        items = (
            self._session.query(EvaluationRunItem)
            .filter(EvaluationRunItem.run_id == run_id, EvaluationRunItem.status == "completed")
            .all()
        )
        if not items:
            return {}
        numeric_keys: set[str] = set()
        for item in items:
            for block in (item.retrieval_metrics, item.rerank_metrics, item.generation_metrics):
                if block:
                    numeric_keys.update(k for k, v in block.items() if isinstance(v, (int, float)))
        aggregated: dict[str, float] = {}
        for key in numeric_keys:
            values = []
            for item in items:
                for block in (item.retrieval_metrics, item.rerank_metrics, item.generation_metrics):
                    if block and key in block and isinstance(block[key], (int, float)):
                        values.append(float(block[key]))
                        break
            if values:
                aggregated[f"mean_{key}"] = mean(values)
        aggregated["item_count"] = len(items)
        return aggregated

    def create_dataset(
        self,
        name: str,
        description: str | None = None,
    ) -> GoldenDataset:
        dataset = GoldenDataset(name=name, description=description)
        self._session.add(dataset)
        self._session.flush()
        return dataset

    def add_dataset_item(
        self,
        dataset_id: uuid.UUID,
        *,
        question: str,
        ground_truth_answer: str | None,
        expected_sources: list[str],
        metadata: dict | None = None,
    ) -> GoldenDatasetItem:
        item = GoldenDatasetItem(
            dataset_id=dataset_id,
            question=question,
            ground_truth_answer=ground_truth_answer,
            expected_sources=expected_sources,
            metadata_=metadata or {},
        )
        self._session.add(item)
        self._session.flush()
        return item

    def list_recent_run_stats(self, limit: int = 20) -> list[EvaluationRun]:
        return (
            self._session.query(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc())
            .limit(limit)
            .all()
        )
