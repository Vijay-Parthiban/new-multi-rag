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
from rag_db.sanitize import strip_null_bytes


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
        """Wipe a dataset and cascade-related runs/run-items."""
        run_ids = [
            row[0]
            for row in self._session.query(EvaluationRun.id)
            .filter(EvaluationRun.dataset_id == dataset_id)
            .all()
        ]
        if run_ids:
            self._session.query(EvaluationRunItem).filter(
                EvaluationRunItem.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            self._session.query(EvaluationRun).filter(
                EvaluationRun.id.in_(run_ids)
            ).delete(synchronize_session=False)

        item_ids = [
            row[0]
            for row in self._session.query(GoldenDatasetItem.id)
            .filter(GoldenDatasetItem.dataset_id == dataset_id)
            .all()
        ]
        if item_ids:
            self._session.query(EvaluationRunItem).filter(
                EvaluationRunItem.dataset_item_id.in_(item_ids)
            ).delete(synchronize_session=False)
            self._session.query(GoldenDatasetItem).filter(
                GoldenDatasetItem.id.in_(item_ids)
            ).delete(synchronize_session=False)

        dataset = self.get_dataset(dataset_id)
        if dataset:
            self._session.delete(dataset)
            self._session.flush()

    def count_runs_for_dataset(self, dataset_id: uuid.UUID) -> int:
        return (
            self._session.query(EvaluationRun)
            .filter(EvaluationRun.dataset_id == dataset_id)
            .count()
        )

    def list_runs_for_dataset(
        self,
        dataset_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> list[EvaluationRun]:
        return (
            self._session.query(EvaluationRun)
            .filter(EvaluationRun.dataset_id == dataset_id)
            .order_by(EvaluationRun.created_at.desc())
            .offset(max(0, skip))
            .limit(limit)
            .all()
        )

    def list_run_items(self, run_id: uuid.UUID) -> list[EvaluationRunItem]:
        return (
            self._session.query(EvaluationRunItem)
            .filter(EvaluationRunItem.run_id == run_id)
            .order_by(EvaluationRunItem.created_at.asc())
            .all()
        )

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
        item.retrieved_chunks = strip_null_bytes(retrieved_chunks)
        item.retrieval_metrics = strip_null_bytes(retrieval_metrics)
        item.reranked_chunks = strip_null_bytes(reranked_chunks)
        item.rerank_metrics = strip_null_bytes(rerank_metrics)
        item.generated_answer = strip_null_bytes(generated_answer)
        item.generation_metrics = strip_null_bytes(generation_metrics)
        self._session.flush()

    def fail_run_item(self, item_id: uuid.UUID, error: str) -> None:
        item = self._session.get(EvaluationRunItem, item_id)
        if item:
            item.status = "failed"
            item.error_message = error
            self._session.flush()

    def aggregate_run_metrics(self, run_id: uuid.UUID) -> dict:
        """Average KPIs grouped by stage, with run config alongside."""
        run = self.get_run(run_id)
        items = (
            self._session.query(EvaluationRunItem)
            .filter(EvaluationRunItem.run_id == run_id, EvaluationRunItem.status == "completed")
            .all()
        )
        if not items:
            return {
                "retrieval": {},
                "reranker": {},
                "generation": {},
                "categories": {},
                "item_count": 0,
                "config": (run.config if run else {}) or {},
            }

        stage_blocks = {
            "retrieval": "retrieval_metrics",
            "reranker": "rerank_metrics",
            "generation": "generation_metrics",
        }
        grouped: dict[str, dict[str, float]] = {
            "retrieval": {},
            "reranker": {},
            "generation": {},
        }

        for stage, attr in stage_blocks.items():
            keys: set[str] = set()
            for item in items:
                block = getattr(item, attr) or {}
                keys.update(k for k, v in block.items() if isinstance(v, (int, float)))
            for key in keys:
                values = [
                    float((getattr(item, attr) or {}).get(key))
                    for item in items
                    if isinstance((getattr(item, attr) or {}).get(key), (int, float))
                ]
                if values:
                    grouped[stage][f"mean_{key}"] = mean(values)

        # A single mean hides the case this breakdown exists for: a strategy that is strong
        # on single-hop lookups and weak on multi-hop reasoning scores the same overall as
        # one that is merely mediocre everywhere. Grouping by the dataset's own question_type
        # shows which kind of question failed. The block shape matches the top-level one, and
        # matches what the page already reads.
        category_of = self._category_by_item_id(items)
        categories: dict[str, dict] = {}
        for category in sorted(set(category_of.values())):
            subset = [i for i in items if category_of.get(i.dataset_item_id) == category]
            block: dict[str, dict] = {"retrieval": {}, "reranker": {}, "generation": {}}
            for stage, attr in stage_blocks.items():
                keys: set[str] = set()
                for item in subset:
                    keys.update(
                        k for k, v in (getattr(item, attr) or {}).items()
                        if isinstance(v, (int, float))
                    )
                for key in keys:
                    values = [
                        float((getattr(item, attr) or {}).get(key))
                        for item in subset
                        if isinstance((getattr(item, attr) or {}).get(key), (int, float))
                    ]
                    if values:
                        block[stage][f"mean_{key}"] = mean(values)
            block["item_count"] = len(subset)
            categories[category] = block

        return {
            **grouped,
            "categories": categories,
            "item_count": len(items),
            "config": (run.config if run else {}) or {},
        }

    def _category_by_item_id(self, items: list[EvaluationRunItem]) -> dict[uuid.UUID, str]:
        """The dataset row's `question_type`, falling back to `category`.

        Rows with neither are left out rather than grouped under a made-up label.
        """
        item_ids = [i.dataset_item_id for i in items]
        if not item_ids:
            return {}
        rows = (
            self._session.query(GoldenDatasetItem.id, GoldenDatasetItem.metadata_)
            .filter(GoldenDatasetItem.id.in_(item_ids))
            .all()
        )
        out: dict[uuid.UUID, str] = {}
        for dataset_item_id, metadata in rows:
            meta = metadata or {}
            label = str(meta.get("question_type") or meta.get("category") or "").strip()
            if label:
                out[dataset_item_id] = label
        return out

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
        expected_sources: list,
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
