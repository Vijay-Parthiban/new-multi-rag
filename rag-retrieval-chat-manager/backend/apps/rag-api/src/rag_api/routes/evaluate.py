from __future__ import annotations

import uuid
from typing import Any

import httpx
from eval_core.dataset_schema import (
    GoldenDatasetItemPayload,
    GoldenDatasetPayload,
    parse_golden_dataset_json,
)
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
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
    # The stores to read. Filling these in runs the evaluation on one pipeline's configuration
    # rather than on the service defaults.
    collection: str | None = None
    embedding_model: str | None = None
    sparse_embedding_model: str | None = None
    # An assistant pipeline reads its Knowledge Product's stores, which means the strategy and
    # the store names travel together. Without a strategy the evaluator reads the legacy scrape
    # collection, which is a different corpus entirely.
    rag_strategy: str | None = None
    opensearch_index: str | None = None
    pg_schema: str | None = None
    pg_table: str | None = None
    # Evaluate a random sample rather than the whole dataset. The seed is stored with the run,
    # so a sample can be reproduced exactly.
    sample_size: int | None = Field(default=None, ge=1, le=500)
    seed: int | None = None
    # RAG execution strategy
    rag_mode: str = "normal"  # "normal" | "self_corrective"
    self_corrective_max_loops: int = 3
    router_enabled: bool = False  # False by default for deterministic offline eval


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


# The built-in evaluation set: question and answer pairs drawn from the Hugging Face
# documentation. It ships with a companion corpus, and every question is answerable only from
# that corpus. A pipeline whose Knowledge Product does not hold those documents therefore
# retrieves nothing and scores near zero, which is a statement about the corpus and not about
# the pipeline. The page says so beside the control.
HF_DATASET = "m-ric/huggingface_doc_qa_eval"
HF_CORPUS_DATASET = "A-Roucher/huggingface_doc"
HF_DATASET_NAME = "HF Doc QA"
_HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
_HF_PAGE = 100
_HF_TIMEOUT_S = 60.0


class HuggingFaceDatasetRequest(BaseModel):
    """Options for importing the built-in evaluation set."""

    replace: bool = False


def _fetch_hf_rows(dataset: str) -> list[dict[str, Any]]:
    """Every row of a dataset, read through the Hub rows API.

    The API pages and caps a page at 100 rows, so this walks it. The built-in set is 65 rows,
    which is a single request.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    with httpx.Client(timeout=_HF_TIMEOUT_S) as client:
        while True:
            response = client.get(
                _HF_ROWS_URL,
                params={
                    "dataset": dataset,
                    "config": "default",
                    "split": "train",
                    "offset": offset,
                    "length": _HF_PAGE,
                },
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "DATASET_FETCH_FAILED",
                        "message": (
                            f"Could not read {dataset} from the Hugging Face Hub "
                            f"(HTTP {response.status_code}). This import needs outbound access "
                            "to datasets-server.huggingface.co."
                        ),
                    },
                )
            payload = response.json()
            batch = payload.get("rows") or []
            rows.extend((row.get("row") or {}) for row in batch)
            offset += len(batch)
            if not batch or offset >= int(payload.get("num_rows_total") or 0):
                return rows


def _hf_rows_to_items(
    rows: list[dict[str, Any]], dataset: str
) -> list[GoldenDatasetItemPayload]:
    """Map the dataset's columns onto the golden dataset shape.

    `source_doc` names the file the answer came from. It becomes the expected source, which is
    what retrieval is scored against.
    """
    items: list[GoldenDatasetItemPayload] = []
    for row in rows:
        question = (row.get("question") or "").strip()
        if not question:
            continue
        source = (row.get("source_doc") or "").strip()
        items.append(
            GoldenDatasetItemPayload(
                question=question,
                ground_truth_answer=(row.get("answer") or "").strip() or None,
                expected_sources=[{"name": source}] if source else [],
                metadata={
                    "hf_dataset": dataset,
                    "source_doc": source,
                    "standalone_score": row.get("standalone_score"),
                    "relevance_score": row.get("relevance_score"),
                },
            )
        )
    return items


@router.post("/datasets/huggingface", response_model=CreateDatasetResponse)
def import_huggingface_dataset(
    body: HuggingFaceDatasetRequest | None = None,
    settings: Settings = Depends(get_settings),
) -> CreateDatasetResponse:
    """Import the built-in evaluation set from the Hugging Face Hub.

    The set is stored as an ordinary golden dataset, so a run against it is an ordinary run and
    its rows are visible in the dataset list. Importing it again with `replace` refreshes it.
    """
    rows = _fetch_hf_rows(HF_DATASET)
    items = _hf_rows_to_items(rows, HF_DATASET)
    if not items:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "DATASET_EMPTY",
                "message": f"{HF_DATASET} returned no usable rows.",
            },
        )
    return _import_dataset_from_payload(
        GoldenDatasetPayload(
            name=HF_DATASET_NAME,
            description=(
                f"{len(items)} question and answer pairs from the Hugging Face documentation "
                f"({HF_DATASET}). The companion corpus is {HF_CORPUS_DATASET}: a pipeline can "
                "only answer these questions if its Knowledge Product holds that corpus."
            ),
            items=items,
        ),
        settings=settings,
        replace=body.replace if body else False,
    )


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


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: uuid.UUID, settings: Settings = Depends(get_settings)) -> Response:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        repo.delete_dataset(dataset_id)
        db.commit()
    return Response(status_code=204)

class DatasetRunsResponse(BaseModel):
    items: list[EvaluationRunStatItem]
    count: int


class EvalRunItemResponse(BaseModel):
    item_id: uuid.UUID
    dataset_item_id: uuid.UUID
    status: str
    question: str | None = None
    expected_sources: list = Field(default_factory=list)
    ground_truth_answer: str | None = None
    generated_answer: str | None = None
    retrieval_metrics: dict | None = None
    rerank_metrics: dict | None = None
    generation_metrics: dict | None = None
    category: str | None = None
    error_message: str | None = None


class EvalRunItemsResponse(BaseModel):
    run_id: uuid.UUID
    count: int
    items: list[EvalRunItemResponse]


@router.get("/datasets/{dataset_id}/runs", response_model=DatasetRunsResponse)
def list_dataset_runs(
    dataset_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    settings: Settings = Depends(get_settings),
) -> DatasetRunsResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        count = repo.count_runs_for_dataset(dataset_id)
        runs = repo.list_runs_for_dataset(dataset_id, skip=skip, limit=limit)
        items = [
            _build_run_stat_item(run, repo.get_run_progress(run.id))
            for run in runs
        ]
    return DatasetRunsResponse(items=items, count=count)


@router.get("/runs/{run_id}/items", response_model=EvalRunItemsResponse)
def list_eval_run_items(
    run_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> EvalRunItemsResponse:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.services.database import get_session_factory

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = EvaluationRepository(db)
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        run_items = repo.list_run_items(run_id)
        items: list[EvalRunItemResponse] = []
        for ri in run_items:
            di = ri.dataset_item
            meta = (di.metadata_ or {}) if di else {}
            items.append(
                EvalRunItemResponse(
                    item_id=ri.id,
                    dataset_item_id=ri.dataset_item_id,
                    status=ri.status,
                    question=di.question if di else None,
                    expected_sources=list(di.expected_sources or []) if di else [],
                    ground_truth_answer=di.ground_truth_answer if di else None,
                    generated_answer=ri.generated_answer,
                    retrieval_metrics=ri.retrieval_metrics,
                    rerank_metrics=ri.rerank_metrics,
                    generation_metrics=ri.generation_metrics,
                    category=meta.get("category"),
                    error_message=ri.error_message,
                )
            )
    return EvalRunItemsResponse(run_id=run_id, count=len(items), items=items)


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
