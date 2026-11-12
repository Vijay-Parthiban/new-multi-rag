"""Uploaded Datasets: manual profiles, their versions, and the files a version holds.

This is the other author of the Synthetic Dataset Creator. A profile binds one Knowledge
Product, a version is a numbered slot, and each version holds at most one single-turn and
one multi-turn dataset. The difference is where the rows come from: here a person uploads a
file, there the eval worker generates the rows.

Both authors share the profile and version tables, separated by `profile.source`, so the
same activation rule and the same Offline Evaluation selection apply to either.
"""

from __future__ import annotations

import logging
import uuid

from eval_core.dataset_schema import (
    UPLOAD_FORMATS,
    parse_golden_dataset_file,
)
from eval_core.dataset_storage import (
    DatasetStorageError,
    delete_dataset as delete_stored_file,
    put_dataset,
    versioned_key,
    resolve_bucket,
)
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

# The read models and the serialisers are shared with the synthetic routes: both authors
# return the same profile and version shape.
from rag_api.routes.synthetic_datasets import (
    ProfileDetailRead,
    ProfileRead,
    VersionItemRead,
    VersionItemsRead,
    VersionRead,
    _dataset_of,
    _error,
    _knowledge_product,
    _profile_to_read,
    _session_factory,
    _settings,
    _vector_collection,
    _version_to_read,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploaded-datasets", tags=["uploaded-datasets"])

SOURCE = "manual"
KINDS = ("single_turn", "multi_turn")
_KIND_LABELS = {"single_turn": "single-turn", "multi_turn": "multi-turn"}


# ── Request models ─────────────────────────────────────────────────────────


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    knowledge_product_id: str = Field(min_length=1)


class VersionCreate(BaseModel):
    version_no: int | None = None
    description: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────


def _manual_profile(repo, profile_id: uuid.UUID):
    profile = repo.get_profile(profile_id)
    if not profile or profile.source != SOURCE:
        raise HTTPException(status_code=404, detail="Uploaded dataset profile not found.")
    return profile


def _manual_version(repo, version_id: uuid.UUID):
    version = repo.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    profile = repo.get_profile(version.profile_id)
    if not profile or profile.source != SOURCE:
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    return version, profile


# ── Profiles ───────────────────────────────────────────────────────────────


@router.get("/profiles", response_model=list[ProfileRead])
async def list_profiles(
    request: Request, knowledge_product_id: str | None = None
) -> list[ProfileRead]:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        return [
            _profile_to_read(repo, profile)
            for profile in repo.list_profiles(
                source=SOURCE, knowledge_product_id=knowledge_product_id
            )
        ]


@router.post("/profiles", response_model=ProfileRead, status_code=201)
async def create_profile(request: Request, body: ProfileCreate) -> ProfileRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    name = body.name.strip()
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        if not name or repo.get_profile_by_name(name, SOURCE):
            raise _error(
                409,
                "PROFILE_NAME_TAKEN",
                f"An uploaded dataset profile named '{name}' already exists.",
            )

    product = await _knowledge_product(settings, body.knowledge_product_id)
    collection, product_name = _vector_collection(product)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        if repo.get_profile_by_name(name, SOURCE):
            raise _error(
                409,
                "PROFILE_NAME_TAKEN",
                f"An uploaded dataset profile named '{name}' already exists.",
            )
        fabric = repo.first_fabric_profile(body.knowledge_product_id)
        profile = repo.create_profile(
            name=name,
            description=(body.description or "").strip() or None,
            knowledge_product_id=body.knowledge_product_id,
            knowledge_product_name=product_name or None,
            qdrant_collection=collection,
            source=SOURCE,
            fabric_profile_id=fabric.id if fabric else None,
        )
        db.commit()
        return _profile_to_read(repo, profile)


@router.get("/profiles/{profile_id}", response_model=ProfileDetailRead)
async def get_profile(request: Request, profile_id: uuid.UUID) -> ProfileDetailRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _manual_profile(repo, profile_id)
        return ProfileDetailRead(
            profile=_profile_to_read(repo, profile),
            versions=[
                _version_to_read(repo, version) for version in repo.list_versions(profile_id)
            ],
        )


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(request: Request, profile_id: uuid.UUID) -> None:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        _manual_profile(repo, profile_id)
        if repo.count_versions(profile_id) > 0:
            raise _error(
                409,
                "PROFILE_HAS_VERSIONS",
                "Delete this profile's versions before you delete the profile.",
            )
        repo.delete_profile(profile_id)
        db.commit()


# ── Versions ───────────────────────────────────────────────────────────────


@router.post("/profiles/{profile_id}/versions", response_model=VersionRead, status_code=201)
def create_version(
    request: Request, profile_id: uuid.UUID, body: VersionCreate
) -> VersionRead:
    """Open a version. It holds no dataset until a file arrives."""
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _manual_profile(repo, profile_id)
        if body.version_no is not None and any(
            version.version_no == body.version_no for version in repo.list_versions(profile_id)
        ):
            raise _error(409, "VERSION_NO_TAKEN", f"Version {body.version_no} already exists.")

        version = repo.create_version(
            profile_id=profile_id,
            version_no=body.version_no or repo.next_version_no(profile_id),
            description=(body.description or "").strip() or None,
            status="empty",
            config={},
            progress={},
            fabric_profile_id=profile.fabric_profile_id,
        )
        db.commit()
        return _version_to_read(repo, version)


@router.post("/versions/{version_id}/activate", response_model=VersionRead)
def activate_version(request: Request, version_id: uuid.UUID) -> VersionRead:
    """Make this version the active one of its profile."""
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        _manual_version(repo, version_id)
        version = repo.activate_version(version_id)
        db.commit()
        return _version_to_read(repo, version)


@router.delete("/versions/{version_id}", status_code=204)
async def delete_version(request: Request, version_id: uuid.UUID) -> None:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        _manual_version(repo, version_id)
        datasets = repo.datasets_for_version(version_id)
        stored = [
            (dataset.storage_bucket, dataset.storage_key)
            for dataset in datasets
            if dataset.storage_bucket and dataset.storage_key
        ]
        for dataset in datasets:
            eval_repo.delete_dataset(dataset.id)
        repo.delete_version(version_id)
        db.commit()

    for bucket, key in stored:
        try:
            await delete_stored_file(settings, bucket=bucket, key=key)
        except DatasetStorageError as exc:
            logger.warning("dataset object delete failed key=%s error=%s", key, exc)


# ── The datasets of one version ────────────────────────────────────────────


@router.post("/versions/{version_id}/datasets", response_model=VersionRead, status_code=201)
async def upload_version_dataset(
    request: Request,
    version_id: uuid.UUID,
    file: UploadFile = File(...),
    kind: str = Form(...),
) -> VersionRead:
    """Upload or replace one kind of this version.

    A second upload of the same kind replaces the first: the old object and its rows go
    first, so a version never holds two datasets of one kind.
    """
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    if kind not in KINDS:
        raise _error(422, "INVALID_KIND", f"kind must be one of {', '.join(KINDS)}.")

    filename = (file.filename or "").strip()
    lower = filename.lower()
    if not any(lower.endswith(fmt) for fmt in UPLOAD_FORMATS):
        raise _error(422, "UNSUPPORTED_FORMAT", f"Upload one of {', '.join(UPLOAD_FORMATS)}.")

    raw = await file.read()
    if not raw.strip():
        raise _error(422, "EMPTY_FILE", "The file is empty.")

    try:
        payload = parse_golden_dataset_file(raw, filename)
    except (ValidationError, ValueError) as exc:
        raise _error(422, "INVALID_DATASET", f"Invalid dataset file: {exc}") from exc

    if payload.kind != kind:
        raise _error(
            422,
            "KIND_MISMATCH",
            (
                f"This file holds {_KIND_LABELS[payload.kind]} rows. "
                f"Upload it as a {_KIND_LABELS[payload.kind]} dataset."
            ),
        )

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version, profile = _manual_version(repo, version_id)
        version_no = version.version_no
        profile_key = str(profile.id)
        kp_id = profile.knowledge_product_id
        profile_name = profile.name
        fabric_profile_id = profile.fabric_profile_id or version.fabric_profile_id

    bucket = resolve_bucket(settings)
    key = versioned_key(kp_id, profile_key, version_no, kind, filename)
    try:
        await put_dataset(settings, bucket=bucket, key=key, data=raw, filename=filename)
    except DatasetStorageError as exc:
        raise _error(503, "STORAGE_UNAVAILABLE", str(exc)) from exc

    replaced: tuple[str, str] | None = None
    try:
        with _session_factory(settings)() as db:
            repo = SyntheticDatasetRepository(db)
            eval_repo = EvaluationRepository(db)
            version, profile = _manual_version(repo, version_id)
            previous = _dataset_of(repo, version_id, kind)
            if previous is not None:
                if previous.storage_bucket and previous.storage_key:
                    replaced = (previous.storage_bucket, previous.storage_key)
                eval_repo.delete_dataset(previous.id)

            dataset = eval_repo.create_dataset(
                name=f"{profile_name} v{version_no} · {_KIND_LABELS[kind]}",
                description=(version.description or None),
                kind=kind,
                profile_id=fabric_profile_id,
                storage_bucket=bucket,
                storage_key=key,
                original_filename=filename,
                source_format=lower.rsplit(".", 1)[-1],
                row_count=len(payload.items),
            )
            dataset.version_id = version.id
            for item in payload.items:
                eval_repo.add_dataset_item(
                    dataset.id,
                    question=item.question,
                    ground_truth_answer=item.ground_truth_answer,
                    expected_sources=item.expected_sources,
                    turns=([turn.model_dump() for turn in item.turns] if item.turns else None),
                    metadata=item.metadata,
                )
            fields: dict[str, object] = {"status": "completed"}
            if kind == "single_turn":
                fields["row_count_single"] = len(payload.items)
            else:
                fields["row_count_multi"] = len(payload.items)
            repo.update_version(version_id, **fields)
            db.commit()
            result = _version_to_read(repo, repo.get_version(version_id))
    except Exception:
        await delete_stored_file(settings, bucket=bucket, key=key)
        raise

    if replaced:
        try:
            await delete_stored_file(settings, bucket=replaced[0], key=replaced[1])
        except DatasetStorageError as exc:
            logger.warning("replaced dataset object delete failed key=%s error=%s", replaced[1], exc)
    return result


@router.delete("/versions/{version_id}/datasets/{kind}", status_code=204)
async def delete_version_dataset(
    request: Request, version_id: uuid.UUID, kind: str
) -> None:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    if kind not in KINDS:
        raise _error(422, "INVALID_KIND", f"kind must be one of {', '.join(KINDS)}.")

    stored: tuple[str, str] | None = None
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        _manual_version(repo, version_id)
        dataset = _dataset_of(repo, version_id, kind)
        if not dataset:
            raise _error(404, "DATASET_NOT_FOUND", "This version has no such dataset.")
        if dataset.storage_bucket and dataset.storage_key:
            stored = (dataset.storage_bucket, dataset.storage_key)
        eval_repo.delete_dataset(dataset.id)
        other = "multi_turn" if kind == "single_turn" else "single_turn"
        fields: dict[str, object] = {
            "status": "completed" if _dataset_of(repo, version_id, other) else "empty"
        }
        if kind == "single_turn":
            fields["row_count_single"] = 0
        else:
            fields["row_count_multi"] = 0
        repo.update_version(version_id, **fields)
        db.commit()

    if stored:
        try:
            await delete_stored_file(settings, bucket=stored[0], key=stored[1])
        except DatasetStorageError as exc:
            logger.warning("dataset object delete failed key=%s error=%s", stored[1], exc)


@router.get("/versions/{version_id}/items", response_model=VersionItemsRead)
def list_version_items(
    request: Request,
    version_id: uuid.UUID,
    kind: str = "single_turn",
    offset: int = 0,
    limit: int = 20,
) -> VersionItemsRead:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    if kind not in KINDS:
        raise _error(422, "INVALID_KIND", f"kind must be one of {', '.join(KINDS)}.")
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        _manual_version(repo, version_id)
        dataset = _dataset_of(repo, version_id, kind)
        if not dataset:
            return VersionItemsRead(count=0, items=[])
        rows = EvaluationRepository(db).list_dataset_items(dataset.id)
        window = rows[max(0, offset) : max(0, offset) + max(1, limit)]
        return VersionItemsRead(
            count=len(rows),
            items=[
                VersionItemRead(
                    id=row.id,
                    question=row.question,
                    ground_truth_answer=row.ground_truth_answer,
                    expected_sources=row.expected_sources or [],
                    turns=row.turns,
                    metadata=row.metadata_ or {},
                )
                for row in window
            ],
        )
