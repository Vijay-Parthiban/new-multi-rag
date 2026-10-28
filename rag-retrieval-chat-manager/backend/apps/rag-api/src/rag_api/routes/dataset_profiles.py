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
from typing import Any

import httpx
from eval_core.dataset_schema import UPLOAD_FORMATS, parse_golden_dataset_file
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from rag_api.dataset_storage import (
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
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[Any] = Field(default_factory=list)
    turns: list[Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        datasets=[
            DatasetFileRead(
                dataset_id=dataset.id,
                kind=dataset.kind,
                filename=dataset.original_filename,
                format=dataset.source_format,
                row_count=dataset.row_count,
                bucket=dataset.storage_bucket,
                key=dataset.storage_key,
                created_at=dataset.created_at,
            )
            for dataset in datasets
        ],
    )


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
        knowledge_product_id = profile.knowledge_product_id
        profile_name = profile.name

    try:
        bucket = await resolve_bucket(settings, knowledge_product_id)
    except DatasetStorageError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "STORAGE_UNAVAILABLE", "message": str(exc)}
        ) from exc

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
            items=[
                DatasetItemPreview(
                    question=item.question,
                    ground_truth_answer=item.ground_truth_answer,
                    expected_sources=item.expected_sources or [],
                    turns=item.turns,
                    metadata=item.metadata_ or {},
                )
                for item in items
            ],
        )


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
