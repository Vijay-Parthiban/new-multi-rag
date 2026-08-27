"""
API routes for offline guardrails golden-dataset evaluation.

Mirrors /evaluate for RAG, but selects a GuardrailsConfig instead of a pipeline.
"""

from __future__ import annotations

import logging
import uuid

from eval_core.guardrails_dataset_schema import (
    GuardrailsGoldenDatasetPayload,
    parse_guardrails_golden_json,
)
from eval_core.guardrails_runner import (
    GuardrailsEvalItem,
    aggregate_guardrails_metrics,
    evaluate_guardrails_item,
)
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError

from rag_db.repositories.guardrails_evaluation_repository import GuardrailsEvaluationRepository
from rag_db.repositories.guardrails_repository import GuardrailsRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guardrails-evaluate", tags=["guardrails-evaluate"])


class DatasetSummary(BaseModel):
    dataset_id: uuid.UUID
    name: str
    description: str | None = None
    item_count: int
    created_at: str | None = None


class CreateDatasetResponse(BaseModel):
    dataset_id: uuid.UUID
    name: str
    item_count: int
    replaced: bool


class DatasetListResponse(BaseModel):
    limit: int
    count: int
    items: list[DatasetSummary]


class CreateGuardrailsEvalRunRequest(BaseModel):
    dataset_id: uuid.UUID
    # Selected GuardrailsConfig — analogue of selecting a RAG pipeline.
    guardrails_config_id: uuid.UUID


class CreateGuardrailsEvalRunResponse(BaseModel):
    run_id: uuid.UUID
    status: str


class GuardrailsEvalRunResponse(BaseModel):
    run_id: uuid.UUID
    dataset_id: uuid.UUID
    config_id: uuid.UUID
    status: str
    config_snapshot: dict
    aggregate_metrics: dict | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class GuardrailsEvalRunListResponse(BaseModel):
    count: int
    items: list[GuardrailsEvalRunResponse]


class GuardrailsEvalRunItemRow(BaseModel):
    run_item_id: uuid.UUID
    dataset_item_id: uuid.UUID
    text: str
    phase: str
    category: str | None = None
    status: str
    skipped: bool
    skip_reason: str | None = None
    expected_blocked: bool
    expected_guard: str | None = None
    actual_blocked: bool
    actual_guard: str | None = None
    correct_block: bool | None = None
    correct_guard: bool | None = None
    guard_results: dict = Field(default_factory=dict)
    error_message: str | None = None


class GuardrailsEvalRunItemsResponse(BaseModel):
    count: int
    items: list[GuardrailsEvalRunItemRow]


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _import_dataset(
    payload: GuardrailsGoldenDatasetPayload,
    *,
    settings: Settings,
    replace: bool,
) -> CreateDatasetResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        try:
            dataset = repo.import_dataset(
                name=payload.name,
                description=payload.description,
                items=[item.model_dump() for item in payload.items],
                replace=replace,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return CreateDatasetResponse(
            dataset_id=dataset.id,
            name=dataset.name,
            item_count=len(payload.items),
            replaced=replace,
        )


@router.post("/datasets/upload", response_model=CreateDatasetResponse)
async def upload_guardrails_dataset(
    file: UploadFile = File(...),
    replace: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> CreateDatasetResponse:
    raw = await file.read()
    try:
        payload = parse_guardrails_golden_json(raw)
    except (ValueError, ValidationError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dataset: {exc}") from exc
    return _import_dataset(payload, settings=settings, replace=replace)


@router.post("/datasets", response_model=CreateDatasetResponse)
def create_guardrails_dataset(
    body: GuardrailsGoldenDatasetPayload,
    settings: Settings = Depends(get_settings),
    replace: bool = Query(False),
) -> CreateDatasetResponse:
    return _import_dataset(body, settings=settings, replace=replace)


@router.get("/datasets", response_model=DatasetListResponse)
def list_guardrails_datasets(
    settings: Settings = Depends(get_settings),
    limit: int = Query(50, ge=1, le=200),
) -> DatasetListResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        rows = repo.list_datasets()[:limit]
        items = [
            DatasetSummary(
                dataset_id=ds.id,
                name=ds.name,
                description=ds.description,
                item_count=count,
                created_at=_iso(ds.created_at),
            )
            for ds, count in rows
        ]
        return DatasetListResponse(limit=limit, count=len(items), items=items)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_guardrails_dataset(
    dataset_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> None:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        if not repo.delete_dataset(dataset_id):
            raise HTTPException(status_code=404, detail="Dataset not found")
        db.commit()


@router.post("/runs", response_model=CreateGuardrailsEvalRunResponse)
def create_guardrails_eval_run(
    body: CreateGuardrailsEvalRunRequest,
    settings: Settings = Depends(get_settings),
) -> CreateGuardrailsEvalRunResponse:
    """
    Run the golden set against the selected GuardrailsConfig synchronously.

    Analogous to creating a RAG eval run with a selected pipeline.
    """
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        eval_repo = GuardrailsEvaluationRepository(db)
        gr_repo = GuardrailsRepository(db)

        dataset = eval_repo.get_dataset(body.dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        # Same GuardrailsConfig row Chat uses when guardrails_config_id is set.
        cfg = gr_repo.get_config(body.guardrails_config_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Guardrails config not found")

        snapshot = {
            "config_id": str(cfg.id),
            "name": cfg.name,
            "mode": cfg.mode,
            "guards": list(cfg.guards or []),
            "settings": getattr(cfg, "settings", None) or {},
            "is_active": bool(cfg.is_active),
        }
        run = eval_repo.create_run(
            dataset_id=body.dataset_id,
            config_id=cfg.id,
            config_snapshot=snapshot,
        )
        db.commit()
        run_id = run.id

        items = eval_repo.list_dataset_items(body.dataset_id)
        results = []
        try:
            for ds_item in items:
                try:
                    outcome = evaluate_guardrails_item(
                        GuardrailsEvalItem(
                            text=ds_item.text,
                            phase=ds_item.phase,
                            expected_blocked=ds_item.expected_blocked,
                            expected_guard=ds_item.expected_guard,
                            category=ds_item.category,
                            metadata=ds_item.metadata_ or {},
                        ),
                        guards=list(cfg.guards or []),
                        mode=cfg.mode,
                        settings=getattr(cfg, "settings", None) or {},
                        guardrails_url=settings.guardrails_url,
                        timeout=settings.guardrails_timeout_s,
                    )
                    eval_repo.save_run_item(
                        run_id=run_id,
                        dataset_item_id=ds_item.id,
                        status="skipped" if outcome.skipped else "completed",
                        skipped=outcome.skipped,
                        skip_reason=outcome.skip_reason,
                        expected_blocked=outcome.expected_blocked,
                        expected_guard=outcome.expected_guard,
                        actual_blocked=outcome.actual_blocked,
                        actual_guard=outcome.actual_guard,
                        correct_block=outcome.correct_block,
                        correct_guard=outcome.correct_guard,
                        guard_results=outcome.guard_results,
                    )
                    results.append(outcome)
                except Exception as exc:
                    logger.exception("Guardrails eval item failed: %s", exc)
                    eval_repo.save_run_item(
                        run_id=run_id,
                        dataset_item_id=ds_item.id,
                        status="failed",
                        skipped=False,
                        skip_reason=None,
                        expected_blocked=ds_item.expected_blocked,
                        expected_guard=ds_item.expected_guard,
                        actual_blocked=False,
                        actual_guard=None,
                        correct_block=None,
                        correct_guard=None,
                        guard_results={},
                        error_message=str(exc),
                    )

            metrics = aggregate_guardrails_metrics(results)
            eval_repo.complete_run(run_id, aggregate_metrics=metrics, status="completed")
            db.commit()
        except Exception as exc:
            logger.exception("Guardrails eval run failed: %s", exc)
            eval_repo.complete_run(
                run_id,
                aggregate_metrics={},
                status="failed",
                error_message=str(exc),
            )
            db.commit()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return CreateGuardrailsEvalRunResponse(run_id=run_id, status="completed")


@router.get("/runs/{run_id}", response_model=GuardrailsEvalRunResponse)
def get_guardrails_eval_run(
    run_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> GuardrailsEvalRunResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return GuardrailsEvalRunResponse(
            run_id=run.id,
            dataset_id=run.dataset_id,
            config_id=run.config_id,
            status=run.status,
            config_snapshot=run.config_snapshot or {},
            aggregate_metrics=run.aggregate_metrics,
            error_message=run.error_message,
            created_at=_iso(run.created_at),
            started_at=_iso(run.started_at),
            completed_at=_iso(run.completed_at),
        )


@router.get("/datasets/{dataset_id}/runs", response_model=GuardrailsEvalRunListResponse)
def list_guardrails_dataset_runs(
    dataset_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> GuardrailsEvalRunListResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        if not repo.get_dataset(dataset_id):
            raise HTTPException(status_code=404, detail="Dataset not found")
        rows, count = repo.list_runs_for_dataset(dataset_id, skip=skip, limit=limit)
        return GuardrailsEvalRunListResponse(
            count=count,
            items=[
                GuardrailsEvalRunResponse(
                    run_id=r.id,
                    dataset_id=r.dataset_id,
                    config_id=r.config_id,
                    status=r.status,
                    config_snapshot=r.config_snapshot or {},
                    aggregate_metrics=r.aggregate_metrics,
                    error_message=r.error_message,
                    created_at=_iso(r.created_at),
                    started_at=_iso(r.started_at),
                    completed_at=_iso(r.completed_at),
                )
                for r in rows
            ],
        )


@router.get("/runs/{run_id}/items", response_model=GuardrailsEvalRunItemsResponse)
def list_guardrails_eval_run_items(
    run_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> GuardrailsEvalRunItemsResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsEvaluationRepository(db)
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        run_items = repo.list_run_items(run_id)
        # Join text/phase/category from dataset items
        ds_items = {
            i.id: i for i in repo.list_dataset_items(run.dataset_id)
        }
        rows: list[GuardrailsEvalRunItemRow] = []
        for ri in run_items:
            di = ds_items.get(ri.dataset_item_id)
            rows.append(
                GuardrailsEvalRunItemRow(
                    run_item_id=ri.id,
                    dataset_item_id=ri.dataset_item_id,
                    text=di.text if di else "",
                    phase=di.phase if di else "input",
                    category=di.category if di else None,
                    status=ri.status,
                    skipped=ri.skipped,
                    skip_reason=ri.skip_reason,
                    expected_blocked=ri.expected_blocked,
                    expected_guard=ri.expected_guard,
                    actual_blocked=ri.actual_blocked,
                    actual_guard=ri.actual_guard,
                    correct_block=ri.correct_block,
                    correct_guard=ri.correct_guard,
                    guard_results=ri.guard_results or {},
                    error_message=ri.error_message,
                )
            )
        return GuardrailsEvalRunItemsResponse(count=len(rows), items=rows)
