from __future__ import annotations

import uuid

from eval_core.dataset_schema import GoldenDatasetPayload, parse_golden_dataset_json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from rag_shared.config import Settings, get_settings

router = APIRouter(prefix="/evaluate", tags=["evaluate"])


class EvalRunConfig(BaseModel):
    retrieval_mode: str = "hybrid"
    retrieve_limit: int = 20
    rerank_enabled: bool = True
    rerank_model: str | None = None
    top_k: int = 5
    generation_model: str | None = None
    k_values: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    collection: str | None = None
    embedding_model: str | None = None
    sparse_embedding_model: str | None = None


class CreateEvalRunRequest(BaseModel):
    dataset_id: uuid.UUID
    config: EvalRunConfig = Field(default_factory=EvalRunConfig)


class CreateEvalRunResponse(BaseModel):
    run_id: uuid.UUID
    status: str


class EvalRunProgress(BaseModel):
    items_total: int = 0
    items_completed: int = 0
    items_failed: int = 0


class EvalRunResponse(BaseModel):
    run_id: uuid.UUID
    dataset_id: uuid.UUID
    status: str
    config: dict
    aggregate_metrics: dict | None = None
    error_message: str | None = None
    progress: EvalRunProgress = Field(default_factory=EvalRunProgress)
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class EvaluationRunStatItem(BaseModel):
    run_id: uuid.UUID
    dataset_id: uuid.UUID
    status: str
    config: dict
    aggregate_metrics: dict | None = None
    error_message: str | None = None
    progress: EvalRunProgress = Field(default_factory=EvalRunProgress)
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class EvaluationStatsResponse(BaseModel):
    limit: int
    count: int
    items: list[EvaluationRunStatItem]


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


def _import_dataset_from_payload(
    payload: GoldenDatasetPayload,
    *,
    settings: Settings,
    replace: bool,
) -> CreateDatasetResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        try:
            dataset = repo.import_dataset(
                name=payload.name,
                description=payload.description,
                items=[item.model_dump() for item in payload.items],
                replace=replace,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        item_count = repo.count_dataset_items(dataset.id)
        db.commit()
        dataset_id = dataset.id
        name = dataset.name

    return CreateDatasetResponse(
        dataset_id=dataset_id,
        name=name,
        item_count=item_count,
        replaced=replace,
    )


@router.post("/datasets", response_model=CreateDatasetResponse)
def create_dataset(
    body: GoldenDatasetPayload,
    replace: bool = False,
    settings: Settings = Depends(get_settings),
) -> CreateDatasetResponse:
    """Create a golden dataset from a JSON body."""
    return _import_dataset_from_payload(body, settings=settings, replace=replace)


@router.post("/datasets/upload", response_model=CreateDatasetResponse)
async def upload_dataset(
    file: UploadFile = File(..., description="Golden dataset JSON file"),
    replace: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> CreateDatasetResponse:
    """Upload a golden dataset JSON file (multipart/form-data)."""
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="file must be a .json file")

    raw = await file.read()
    if not raw.strip():
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    try:
        payload = parse_golden_dataset_json(raw)
    except (ValidationError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid dataset JSON: {exc}") from exc

    return _import_dataset_from_payload(payload, settings=settings, replace=replace)


@router.get("/datasets", response_model=DatasetListResponse)
def list_datasets(
    limit: int = 50,
    settings: Settings = Depends(get_settings),
) -> DatasetListResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        datasets = repo.list_datasets(limit=limit)
        items = [
            DatasetSummary(
                dataset_id=dataset.id,
                name=dataset.name,
                description=dataset.description,
                item_count=repo.count_dataset_items(dataset.id),
                created_at=_dt_iso(dataset.created_at),
            )
            for dataset in datasets
        ]

    return DatasetListResponse(limit=limit, count=len(items), items=items)


@router.get("/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(dataset_id: uuid.UUID, settings: Settings = Depends(get_settings)) -> DatasetSummary:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return DatasetSummary(
            dataset_id=dataset.id,
            name=dataset.name,
            description=dataset.description,
            item_count=repo.count_dataset_items(dataset.id),
            created_at=_dt_iso(dataset.created_at),
        )


@router.post("/runs", response_model=CreateEvalRunResponse)
def create_eval_run(request: Request, body: CreateEvalRunRequest) -> CreateEvalRunResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    settings = request.app.state.settings
    queue = request.app.state.queue
    session_factory = get_session_factory(settings)

    with session_factory() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(body.dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        run = repo.create_run(body.dataset_id, body.config.model_dump())
        db.commit()
        run_id = run.id

    queue.enqueue("eval_worker.tasks.run_evaluation", str(run_id))
    return CreateEvalRunResponse(run_id=run_id, status="queued")


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
def get_eval_run(run_id: uuid.UUID, request: Request) -> EvalRunResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    settings = request.app.state.settings
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        progress = repo.get_run_progress(run.id)
        return _build_run_response(run, progress)


def _dt_iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _run_error_message(status: str, aggregate_metrics: dict | None) -> str | None:
    if status != "failed" or not aggregate_metrics:
        return None
    error = aggregate_metrics.get("error")
    return str(error) if error else None


def _build_run_response(run, progress: dict) -> EvalRunResponse:
    return EvalRunResponse(
        run_id=run.id,
        dataset_id=run.dataset_id,
        status=run.status,
        config=run.config,
        aggregate_metrics=run.aggregate_metrics,
        error_message=_run_error_message(run.status, run.aggregate_metrics),
        progress=EvalRunProgress(**progress),
        created_at=_dt_iso(run.created_at),
        started_at=_dt_iso(run.started_at),
        completed_at=_dt_iso(run.completed_at),
    )


def _build_run_stat_item(run, progress: dict) -> EvaluationRunStatItem:
    return EvaluationRunStatItem(
        run_id=run.id,
        dataset_id=run.dataset_id,
        status=run.status,
        config=run.config,
        aggregate_metrics=run.aggregate_metrics,
        error_message=_run_error_message(run.status, run.aggregate_metrics),
        progress=EvalRunProgress(**progress),
        created_at=_dt_iso(run.created_at),
        started_at=_dt_iso(run.started_at),
        completed_at=_dt_iso(run.completed_at),
    )


@router.get("/stats", response_model=EvaluationStatsResponse)
def get_evaluation_stats(
    limit: int = 20,
    settings: Settings = Depends(get_settings),
) -> EvaluationStatsResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        runs = repo.list_recent_run_stats(limit=limit)
        items = [
            _build_run_stat_item(run, repo.get_run_progress(run.id))
            for run in runs
        ]

    return EvaluationStatsResponse(limit=limit, count=len(items), items=items)
