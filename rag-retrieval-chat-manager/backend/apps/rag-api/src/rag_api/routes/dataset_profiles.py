"""Dataset Fabric: profiles and their uploaded golden datasets.

A profile is the unit the Offline Evaluation page selects. It names a purpose, links to at
most one pipeline, and holds one or more uploaded datasets per kind. The uploaded file is
written to MinIO — into the pipeline's Knowledge Product document bucket when the profile
is linked, and into one shared bucket when it is not — and the parsed rows become a
`golden_datasets` row so the evaluator needs no change.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from eval_core.dataset_schema import (
    UPLOAD_FORMATS,
    GoldenDatasetItemPayload,
    dataset_items_to_jsonl,
    parse_golden_dataset_file,
)
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from eval_core.dataset_storage import (
    DatasetStorageError,
    delete_dataset as delete_stored_file,
    object_key,
    put_dataset,
    resolve_bucket,
)
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dataset-profiles", tags=["dataset-profiles"])

KINDS = ("single_turn", "multi_turn")
_KIND_LABELS = {"single_turn": "single-turn", "multi_turn": "multi-turn"}
_INGESTION_TIMEOUT_S = 30.0


# ── Response models ────────────────────────────────────────────────────────


class DatasetFileRead(BaseModel):
    dataset_id: uuid.UUID
    kind: str
    filename: str | None = None
    format: str | None = None
    row_count: int | None = None
    bucket: str | None = None
    key: str | None = None
    created_at: datetime | None = None


class DatasetProfileRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    pipeline_slug: str | None = None
    pipeline_name: str | None = None
    knowledge_product_id: str | None = None
    knowledge_product_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    datasets: list[DatasetFileRead] = Field(default_factory=list)


class DatasetProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    # None means "yet to be linked". A slug is resolved against the ingestion service
    # when the profile is created, so the list can render without that call.
    pipeline_slug: str | None = None


class DatasetProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    pipeline_slug: str | None = None


class DatasetItemPreview(BaseModel):
    id: uuid.UUID
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[Any] = Field(default_factory=list)
    turns: list[Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetItemUpdate(BaseModel):
    """A partial row edit. Only the keys the caller sends change."""

    question: str | None = None
    ground_truth_answer: str | None = None
    expected_sources: list[Any] | None = None
    turns: list[Any] | None = None
    question_type: str | None = None
    expected_behavior: Literal["answer_from_corpus", "refuse_or_abstain"] | None = None


class DatasetPreviewRead(BaseModel):
    dataset_id: uuid.UUID
    profile_id: uuid.UUID
    filename: str | None = None
    kind: str
    row_count: int | None = None
    bucket: str | None = None
    key: str | None = None
    items: list[DatasetItemPreview] = Field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session_factory(settings: Settings):
    from rag_db.services.database import get_session_factory

    return get_session_factory(settings)


def _headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.api_key} if settings.api_key else {}


async def _pipeline_snapshot(settings: Settings, slug: str) -> tuple[str | None, str | None, str | None]:
    """`(pipeline_name, knowledge_product_id, knowledge_product_name)` for a slug.

    The pipeline lives in the ingestion service, so this is one HTTP read. Its failure is
    a 503 and not a silent unlinked profile: the whole point of the link is that the files
    land in that pipeline's bucket.
    """
    base = settings.ingestion_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_INGESTION_TIMEOUT_S) as client:
            response = await client.get(
                f"{base}/api/pipelines/by-slug/{slug}", headers=_headers(settings)
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "INGESTION_SERVICE_UNAVAILABLE",
                "message": f"Cannot reach the ingestion service: {exc}",
            },
        ) from exc

    if response.status_code == 404:
        raise HTTPException(
            status_code=422,
            detail={"code": "PIPELINE_NOT_FOUND", "message": f"No pipeline has the slug '{slug}'."},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail={"code": "INGESTION_SERVICE_ERROR", "message": response.text[:500]},
        )

    pipeline = response.json()
    product = pipeline.get("knowledge_product") or {}
    return pipeline.get("name"), product.get("id"), product.get("name")


def _dataset_to_read(dataset) -> DatasetFileRead:
    return DatasetFileRead(
        dataset_id=dataset.id,
        kind=dataset.kind,
        filename=dataset.original_filename,
        format=dataset.source_format,
        row_count=dataset.row_count,
        bucket=dataset.storage_bucket,
        key=dataset.storage_key,
        created_at=dataset.created_at,
    )


def _profile_to_read(profile) -> DatasetProfileRead:
    datasets = sorted(
        profile.datasets or [], key=lambda d: d.created_at or datetime.min, reverse=True
    )
    return DatasetProfileRead(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        pipeline_slug=profile.pipeline_slug,
        pipeline_name=profile.pipeline_name,
        knowledge_product_id=profile.knowledge_product_id,
        knowledge_product_name=profile.knowledge_product_name,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        datasets=[_dataset_to_read(dataset) for dataset in datasets],
    )


def _sources(values: list[Any]) -> list[dict[str, Any]]:
    """`["a.pdf", {"name": "b.pdf", "page": 3}]` as the stored shape. Blanks are dropped."""
    out: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, str):
            name, page = value.strip(), None
        elif isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            page = value.get("page")
        else:
            continue
        if not name:
            continue
        if any(existing["name"] == name for existing in out):
            continue
        entry: dict[str, Any] = {"name": name}
        if page not in (None, ""):
            entry["page"] = page
        out.append(entry)
    return out


def _item_preview(item) -> DatasetItemPreview:
    return DatasetItemPreview(
        id=item.id,
        question=item.question,
        ground_truth_answer=item.ground_truth_answer,
        expected_sources=item.expected_sources or [],
        turns=item.turns,
        metadata=item.metadata_ or {},
    )


async def store_snapshot(settings, db, repo, dataset, *, profile_id, kind) -> None:
    """Rewrite the dataset's canonical JSONL object and point the row at it.

    The file is written before the commit, so no row exists without the snapshot it
    belongs to. The previous object is deleted after the commit, which is also what takes
    a file out of a Knowledge Product bucket an older build wrote into. Call this after
    the item rows are written; it commits the row changes itself.
    """
    # `list_dataset_items` returns insertion order, so the file keeps the same row order
    # after an edit.
    rows = repo.list_dataset_items(dataset.id)
    data = dataset_items_to_jsonl(
        {
            "question": i.question,
            "ground_truth_answer": i.ground_truth_answer,
            "expected_sources": i.expected_sources or [],
            "turns": i.turns,
            "metadata": i.metadata_ or {},
        }
        for i in rows
    )
    stem = Path(dataset.original_filename).stem if dataset.original_filename else f"{kind}_feedback"
    filename = f"{stem}.jsonl"
    bucket = resolve_bucket(settings)
    new_key = object_key(str(profile_id), kind, filename)
    old_bucket, old_key = dataset.storage_bucket, dataset.storage_key

    try:
        await put_dataset(settings, bucket=bucket, key=new_key, data=data, filename=filename)
    except DatasetStorageError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_UNAVAILABLE", "message": str(exc)}
        ) from exc

    dataset.storage_bucket = bucket
    dataset.storage_key = new_key
    dataset.original_filename = filename
    dataset.source_format = "jsonl"
    dataset.row_count = repo.count_dataset_items(dataset.id)
    try:
        db.commit()
    except Exception:
        if new_key != old_key:
            await delete_stored_file(settings, bucket=bucket, key=new_key)
        raise

    if old_key and (old_bucket, old_key) != (bucket, new_key):
        await delete_stored_file(settings, bucket=old_bucket, key=old_key)


# ── Profiles ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[DatasetProfileRead])
def list_profiles(request: Request, pipeline_slug: str | None = None) -> list[DatasetProfileRead]:
    """Profiles, newest first. `pipeline_slug` narrows to the ones linked to that pipeline."""
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = DatasetProfileRepository(db)
        return [_profile_to_read(p) for p in repo.list_profiles(pipeline_slug=pipeline_slug)]


@router.post("", response_model=DatasetProfileRead, status_code=201)
async def create_profile(request: Request, body: DatasetProfileCreate) -> DatasetProfileRead:
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository

    settings = _settings(request)
    name = body.name.strip()
    slug = (body.pipeline_slug or "").strip() or None
    pipeline_name = knowledge_product_id = knowledge_product_name = None
    if slug:
        pipeline_name, knowledge_product_id, knowledge_product_name = await _pipeline_snapshot(
            settings, slug
        )

    with _session_factory(settings)() as db:
        repo = DatasetProfileRepository(db)
        if repo.get_by_name(name):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROFILE_EXISTS",
                    "message": f"A dataset profile named '{name}' already exists.",
                },
            )
        profile = repo.create(
            name=name,
            description=(body.description or "").strip() or None,
            pipeline_slug=slug,
            pipeline_name=pipeline_name,
            knowledge_product_id=knowledge_product_id,
            knowledge_product_name=knowledge_product_name,
        )
        db.commit()
        return _profile_to_read(repo.get(profile.id))


@router.patch("/{profile_id}", response_model=DatasetProfileRead)
async def update_profile(
    request: Request, profile_id: uuid.UUID, body: DatasetProfileUpdate
) -> DatasetProfileRead:
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository

    settings = _settings(request)
    slug_changed = body.pipeline_slug is not None
    slug = (body.pipeline_slug or "").strip() or None
    pipeline_name = knowledge_product_id = knowledge_product_name = None
    if slug_changed and slug:
        pipeline_name, knowledge_product_id, knowledge_product_name = await _pipeline_snapshot(
            settings, slug
        )

    with _session_factory(settings)() as db:
        repo = DatasetProfileRepository(db)
        profile = repo.get(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Dataset profile not found.")
        if body.name is not None:
            name = body.name.strip()
            other = repo.get_by_name(name)
            if other and other.id != profile.id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "PROFILE_EXISTS",
                        "message": f"A dataset profile named '{name}' already exists.",
                    },
                )
            profile.name = name
        if body.description is not None:
            profile.description = body.description.strip() or None
        if slug_changed:
            profile.pipeline_slug = slug
            profile.pipeline_name = pipeline_name
            profile.knowledge_product_id = knowledge_product_id
            profile.knowledge_product_name = knowledge_product_name
        db.commit()
        return _profile_to_read(repo.get(profile_id))


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(request: Request, profile_id: uuid.UUID) -> None:
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = DatasetProfileRepository(db)
        profile = repo.get(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Dataset profile not found.")
        datasets = repo.delete(profile)
        db.commit()

    for dataset in datasets:
        if dataset.storage_bucket and dataset.storage_key:
            await delete_stored_file(
                settings, bucket=dataset.storage_bucket, key=dataset.storage_key
            )


# ── Uploaded datasets ──────────────────────────────────────────────────────


@router.post("/{profile_id}/datasets", response_model=DatasetFileRead, status_code=201)
async def upload_dataset(
    request: Request,
    profile_id: uuid.UUID,
    file: UploadFile = File(...),
    kind: str = Form(...),
) -> DatasetFileRead:
    """Parse an upload, write the file to MinIO, and import its rows.

    A new dataset row is created on every upload instead of replacing the previous one, so
    an evaluation run that points at an older upload stays readable. The page reads the
    newest row for the selected kind.
    """
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    settings = _settings(request)
    if kind not in KINDS:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_KIND", "message": f"kind must be one of {', '.join(KINDS)}."},
        )

    filename = (file.filename or "").strip()
    lower = filename.lower()
    if not any(lower.endswith(fmt) for fmt in UPLOAD_FORMATS):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_FORMAT",
                "message": f"Upload one of {', '.join(UPLOAD_FORMATS)}.",
            },
        )
    raw = await file.read()
    if not raw.strip():
        raise HTTPException(
            status_code=422, detail={"code": "EMPTY_FILE", "message": "The file is empty."}
        )

    try:
        payload = parse_golden_dataset_file(raw, filename)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_DATASET", "message": f"Invalid dataset file: {exc}"},
        ) from exc

    if payload.kind != kind:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "KIND_MISMATCH",
                "message": (
                    f"This file holds {_KIND_LABELS[payload.kind]} rows. "
                    f"Upload it in the {_KIND_LABELS[payload.kind]} section."
                ),
            },
        )

    with _session_factory(settings)() as db:
        profile = DatasetProfileRepository(db).get(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Dataset profile not found.")
        profile_name = profile.name

    bucket = resolve_bucket(settings)

    key = object_key(str(profile_id), kind, filename)
    try:
        await put_dataset(settings, bucket=bucket, key=key, data=raw, filename=filename)
    except DatasetStorageError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_UNAVAILABLE", "message": str(exc)}
        ) from exc

    dataset_name = f"{profile_name}::{kind}::{uuid.uuid4().hex[:6]}"
    try:
        with _session_factory(settings)() as db:
            repo = EvaluationRepository(db)
            dataset = repo.create_dataset(
                dataset_name,
                description=f"{filename} uploaded to {profile_name}",
                kind=kind,
                profile_id=profile_id,
                storage_bucket=bucket,
                storage_key=key,
                original_filename=filename,
                source_format=lower.rsplit(".", 1)[-1],
                row_count=len(payload.items),
            )
            for item in payload.items:
                repo.add_dataset_item(
                    dataset.id,
                    question=item.question,
                    ground_truth_answer=item.ground_truth_answer,
                    expected_sources=item.expected_sources,
                    turns=(
                        [turn.model_dump() for turn in item.turns] if item.turns else None
                    ),
                    metadata=item.metadata,
                )
            db.commit()
            return DatasetFileRead(
                dataset_id=dataset.id,
                kind=kind,
                filename=filename,
                format=lower.rsplit(".", 1)[-1],
                row_count=len(payload.items),
                bucket=bucket,
                key=key,
                created_at=dataset.created_at,
            )
    except Exception:
        # The file is already in the bucket. Remove it so a failed import does not leave an
        # object no row points at.
        await delete_stored_file(settings, bucket=bucket, key=key)
        raise


@router.get("/{profile_id}/datasets/{dataset_id}", response_model=DatasetPreviewRead)
def preview_dataset(
    request: Request, profile_id: uuid.UUID, dataset_id: uuid.UUID
) -> DatasetPreviewRead:
    """The rows of one uploaded dataset, so clicking it shows what it holds."""
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset or dataset.profile_id != profile_id:
            raise HTTPException(status_code=404, detail="Dataset not found in this profile.")
        items = repo.list_dataset_items(dataset_id)
        return DatasetPreviewRead(
            dataset_id=dataset.id,
            profile_id=profile_id,
            filename=dataset.original_filename,
            kind=dataset.kind,
            row_count=dataset.row_count or len(items),
            bucket=dataset.storage_bucket,
            key=dataset.storage_key,
            items=[_item_preview(item) for item in items],
        )


@router.patch(
    "/{profile_id}/datasets/{dataset_id}/items/{item_id}", response_model=DatasetItemPreview
)
async def update_dataset_item(
    request: Request,
    profile_id: uuid.UUID,
    dataset_id: uuid.UUID,
    item_id: uuid.UUID,
    body: DatasetItemUpdate,
) -> DatasetItemPreview:
    """Edit one row of a dataset.

    The canonical JSONL object is rewritten, so the file and the rows always agree.
    """
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    settings = _settings(request)
    sent = body.model_fields_set
    with _session_factory(settings)() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset or dataset.profile_id != profile_id:
            raise HTTPException(status_code=404, detail="Dataset not found in this profile.")
        item = repo.get_dataset_item(item_id)
        if not item or item.dataset_id != dataset_id:
            raise HTTPException(status_code=404, detail="Dataset row not found.")

        question = body.question if "question" in sent else item.question
        answer = (
            body.ground_truth_answer
            if "ground_truth_answer" in sent
            else item.ground_truth_answer
        )
        sources = (
            body.expected_sources
            if "expected_sources" in sent
            else (item.expected_sources or [])
        )
        turns = body.turns if "turns" in sent else item.turns

        metadata = dict(item.metadata_ or {})
        if "question_type" in sent:
            label = (body.question_type or "").strip()
            if label:
                metadata["question_type"] = label
            else:
                metadata.pop("question_type", None)
        if body.expected_behavior:
            metadata["expected_behavior"] = body.expected_behavior
        # An abstain row has no reference to score against, so it holds neither.
        if metadata.get("expected_behavior") == "refuse_or_abstain":
            answer, sources = None, []

        if dataset.kind == "single_turn" and turns:
            raise HTTPException(
                status_code=422,
                detail={"code": "KIND_MISMATCH", "message": "A single-turn row cannot hold turns."},
            )
        if dataset.kind == "multi_turn" and not turns:
            raise HTTPException(
                status_code=422,
                detail={"code": "KIND_MISMATCH", "message": "A multi-turn row needs its turns."},
            )
        # The row's question is its last user turn: derived when the turns change without
        # a question, and when the question arrives empty.
        question = (question or "").strip()
        if turns and ("question" not in sent or not question):
            question = next(
                (
                    str(turn.get("content") or "")
                    for turn in reversed(turns)
                    if turn.get("role") == "user"
                ),
                question,
            )

        try:
            payload = GoldenDatasetItemPayload.model_validate(
                {
                    "question": question,
                    "ground_truth_answer": answer,
                    "expected_sources": _sources(sources),
                    "turns": turns,
                    "metadata": metadata,
                }
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"code": "INVALID_ROW", "message": str(exc)}
            ) from exc

        item.question = payload.question
        item.ground_truth_answer = payload.ground_truth_answer
        item.expected_sources = payload.expected_sources
        # JSONB needs plain dicts; the payload holds validated models.
        item.turns = [turn.model_dump() for turn in payload.turns] if payload.turns else None
        item.metadata_ = payload.metadata
        db.flush()
        await store_snapshot(settings, db, repo, dataset, profile_id=profile_id, kind=dataset.kind)
        return _item_preview(item)


@router.delete("/{profile_id}/datasets/{dataset_id}", status_code=204)
async def delete_dataset(request: Request, profile_id: uuid.UUID, dataset_id: uuid.UUID) -> None:
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = EvaluationRepository(db)
        dataset = repo.get_dataset(dataset_id)
        if not dataset or dataset.profile_id != profile_id:
            raise HTTPException(status_code=404, detail="Dataset not found in this profile.")
        bucket, key = dataset.storage_bucket, dataset.storage_key
        repo.delete_dataset(dataset_id)
        db.commit()

    if bucket and key:
        await delete_stored_file(settings, bucket=bucket, key=key)
