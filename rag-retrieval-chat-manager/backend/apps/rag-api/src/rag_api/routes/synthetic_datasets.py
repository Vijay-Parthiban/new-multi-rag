"""Synthetic Dataset Creator: profiles, versions, and the datasets a version holds.

A profile binds one Knowledge Product to the Qdrant collection its chunks live in. A version
is a numbered slot per dataset kind: one single-turn dataset and one multi-turn dataset, each
with its own configuration and its own generation run. The rows are ordinary golden datasets,
so Offline Evaluation selects them with no change.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

import httpx
from eval_core.dataset_storage import (
    DatasetStorageError,
    delete_dataset as delete_stored_file,
    resolve_bucket,
)
from eval_core.synthesis_constants import (
    EVOLUTION_NAMES,
    KIND_CONFIG_KEY,
    KIND_WORD,
    RAG_SAFE_EVOLUTIONS,
)
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from rag_shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/synthetic-datasets", tags=["synthetic-datasets"])

DatasetKind = Literal["single_turn", "multi_turn"]
DATASET_KINDS: tuple[str, ...] = ("single_turn", "multi_turn")
_INGESTION_TIMEOUT_S = 10.0


# ── Response models ────────────────────────────────────────────────────────


class ProfileRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    knowledge_product_id: str
    knowledge_product_name: str | None = None
    qdrant_collection: str
    version_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VersionDatasetRead(BaseModel):
    id: uuid.UUID
    kind: str
    row_count: int | None = None
    status: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class VersionRead(BaseModel):
    id: uuid.UUID
    version_no: int
    description: str | None = None
    status: str
    progress: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    row_count_single: int = 0
    row_count_multi: int = 0
    fabric_profile_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    datasets: list[VersionDatasetRead] = Field(default_factory=list)


class ProfileDetailRead(BaseModel):
    profile: ProfileRead
    versions: list[VersionRead] = Field(default_factory=list)


class VersionItemRead(BaseModel):
    id: uuid.UUID
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[Any] = Field(default_factory=list)
    turns: list[Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VersionItemsRead(BaseModel):
    count: int
    items: list[VersionItemRead] = Field(default_factory=list)


# ── Request models ─────────────────────────────────────────────────────────


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    knowledge_product_id: str = Field(min_length=1)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class FiltrationConfigBody(BaseModel):
    enabled: bool = True
    threshold: float = 0.5
    max_retries: int = 3


class StylingBody(BaseModel):
    task: str | None = None
    scenario: str | None = None
    input_format: str | None = None
    expected_output_format: str | None = None


class ConversationalStylingBody(BaseModel):
    scenario_context: str | None = None
    conversational_task: str | None = None
    participant_roles: str | None = None


class KindConfig(BaseModel):
    """One dataset's generation settings. The single and multi datasets each carry one."""

    rows: int = 7
    # Multi-turn only. Kept on the shared model so one validator covers both kinds.
    turns: int = 2
    chunks_per_context: int = 4
    max_goldens_per_context: int = 2
    filtration: FiltrationConfigBody = Field(default_factory=FiltrationConfigBody)
    evolutions: list[str] = Field(default_factory=lambda: list(RAG_SAFE_EVOLUTIONS))
    num_evolutions: int = 1
    styling: StylingBody = Field(default_factory=StylingBody)
    conversational_styling: ConversationalStylingBody = Field(
        default_factory=ConversationalStylingBody
    )


class VersionCreate(BaseModel):
    version_no: int | None = None
    description: str | None = None
    model: str = ""
    fabric_profile_id: uuid.UUID | None = None
    # Which datasets this version starts with. The other kind can be added later.
    # Kept as plain strings so an unknown value returns a coded 422, not a pydantic list.
    kinds: list[str] = Field(default_factory=lambda: ["single_turn"])
    single: KindConfig | None = None
    multi: KindConfig | None = None


class DatasetCreate(BaseModel):
    kind: DatasetKind
    config: KindConfig = Field(default_factory=KindConfig)


class DatasetUpdate(BaseModel):
    config: KindConfig


# ── Helpers ────────────────────────────────────────────────────────────────


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session_factory(settings: Settings):
    from rag_db.services.database import get_session_factory

    return get_session_factory(settings)


def _headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.api_key} if settings.api_key else {}


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _knowledge_product(settings: Settings, product_id: str) -> dict:
    base = settings.ingestion_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_INGESTION_TIMEOUT_S) as client:
            response = await client.get(
                f"{base}/api/knowledge-products/{product_id}", headers=_headers(settings)
            )
    except httpx.RequestError as exc:
        raise _error(
            503,
            "INGESTION_SERVICE_UNAVAILABLE",
            f"Cannot reach the ingestion service: {exc}",
        ) from exc

    if response.status_code == 404:
        raise _error(
            422,
            "UNKNOWN_KNOWLEDGE_PRODUCT",
            f"No Knowledge Product has the id '{product_id}'.",
        )
    if response.status_code != 200:
        raise _error(422, "INGESTION_SERVICE_ERROR", response.text[:500])
    return response.json()


def _vector_collection(product: dict) -> tuple[str, str]:
    """`(collection_name, product_name)` from the product's enabled Qdrant destination."""
    for destination in product.get("destinations") or []:
        if destination.get("destination_type") != "vector_qdrant" or not destination.get("enabled"):
            continue
        collection = str((destination.get("config") or {}).get("collection_name") or "").strip()
        if not collection:
            raise _error(
                422,
                "VECTOR_COLLECTION_MISSING",
                "The Qdrant destination has no collection name.",
            )
        return collection, str(product.get("name") or "")
    raise _error(
        422,
        "NO_VECTOR_DESTINATION",
        "Enable the Dense Vector Store (Qdrant) destination on this Knowledge Product first.",
    )


def _dataset_name(profile, version_no: int, kind: str) -> str:
    return f"{profile.name} v{version_no} · {KIND_WORD[kind]}"


def _profile_to_read(repo, profile) -> ProfileRead:
    return ProfileRead(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        knowledge_product_id=profile.knowledge_product_id,
        knowledge_product_name=profile.knowledge_product_name,
        qdrant_collection=profile.qdrant_collection,
        version_count=repo.count_versions(profile.id),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _version_to_read(repo, version) -> VersionRead:
    progress = version.progress or {}
    kind_progress = progress.get("kinds") or {}
    config = version.config or {}
    datasets = repo.datasets_for_version(version.id)
    return VersionRead(
        id=version.id,
        version_no=version.version_no,
        description=version.description,
        status=version.status,
        progress=progress,
        error_message=version.error_message,
        row_count_single=version.row_count_single or 0,
        row_count_multi=version.row_count_multi or 0,
        fabric_profile_id=version.fabric_profile_id,
        config=config,
        created_at=version.created_at,
        started_at=version.started_at,
        completed_at=version.completed_at,
        datasets=[
            VersionDatasetRead(
                id=dataset.id,
                kind=dataset.kind,
                row_count=dataset.row_count or 0,
                # Versions generated before per-kind progress carry no status. Rows on
                # disk mean the dataset completed, which is what the page must show.
                status=(kind_progress.get(dataset.kind) or {}).get("status")
                or ("completed" if (dataset.row_count or 0) > 0 else None),
                progress=kind_progress.get(dataset.kind) or {},
                config=config.get(KIND_CONFIG_KEY.get(dataset.kind, "single")) or {},
                created_at=dataset.created_at,
            )
            for dataset in datasets
        ],
    )


def _validate_kind_config(kind: str, config: KindConfig) -> None:
    if not 1 <= config.rows <= 100:
        raise _error(422, "INVALID_ROWS", "`rows` must be between 1 and 100.")
    if kind == "multi_turn" and not 2 <= config.turns <= 6:
        raise _error(422, "INVALID_TURNS", "`turns` must be between 2 and 6.")
    if not config.evolutions:
        raise _error(422, "INVALID_EVOLUTIONS", "Pick at least one evolution.")
    unknown = [name for name in config.evolutions if name not in EVOLUTION_NAMES]
    if unknown:
        raise _error(
            422, "INVALID_EVOLUTIONS", f"Unknown evolution: {', '.join(sorted(unknown))}."
        )
    if not 1 <= config.num_evolutions <= 3:
        raise _error(422, "INVALID_NUM_EVOLUTIONS", "`num_evolutions` must be between 1 and 3.")
    if not 1 <= config.chunks_per_context <= 10:
        raise _error(422, "INVALID_CHUNKS", "`chunks_per_context` must be between 1 and 10.")
    if not 1 <= config.max_goldens_per_context <= 5:
        raise _error(422, "INVALID_GOLDENS", "`max_goldens_per_context` must be between 1 and 5.")


def _version_config(body: VersionCreate) -> tuple[list[str], dict]:
    """The kinds this version starts with, and the stored config for all kinds."""
    kinds = list(dict.fromkeys(body.kinds))
    if not kinds:
        raise _error(422, "NO_DATASET_KINDS", "Pick at least one dataset type.")
    for kind in kinds:
        if kind not in DATASET_KINDS:
            raise _error(422, "INVALID_KIND", f"`{kind}` is not a dataset kind.")

    config: dict[str, Any] = {"model": body.model.strip()}
    for kind in kinds:
        kind_config = body.single if kind == "single_turn" else body.multi
        if kind_config is None:
            raise _error(
                422,
                "MISSING_CONFIG",
                f"The {KIND_WORD[kind]}-turn dataset needs a configuration.",
            )
        _validate_kind_config(kind, kind_config)
        config[KIND_CONFIG_KEY[kind]] = kind_config.model_dump(mode="json")

    if not body.model.strip():
        raise _error(
            422,
            "MODEL_NOT_CONFIGURED",
            "Pick a chat model, and set OPENAI_API_KEY for the LiteLLM proxy.",
        )
    return kinds, config


def _check_model(settings: Settings) -> None:
    if not settings.openai_api_key:
        raise _error(
            422,
            "MODEL_NOT_CONFIGURED",
            "Set OPENAI_API_KEY for the LiteLLM proxy before you generate a dataset.",
        )


# A run may reach two hours on a slow model. The old one hour cap cut the job before the
# second dataset started.
SYNTHESIS_JOB_TIMEOUT_SECONDS = 7200


def _enqueue(request: Request, version_id: uuid.UUID, kinds: list[str]) -> None:
    """Queue one job per dataset kind.

    Each kind then has its own timeout and its own failure, so a slow multi-turn run
    cannot hold the single-turn one, and two workers can run them side by side.
    """
    for kind in kinds:
        request.app.state.queue.enqueue(
            "eval_worker.tasks.run_synthesis",
            str(version_id),
            [kind],
            job_timeout=SYNTHESIS_JOB_TIMEOUT_SECONDS,
        )


def _create_dataset_row(eval_repo, settings: Settings, profile, version, kind: str, config: dict):
    dataset = eval_repo.create_dataset(
        name=_dataset_name(profile, version.version_no, kind),
        description=version.description,
        kind=kind,
        profile_id=version.fabric_profile_id,
        storage_bucket=resolve_bucket(settings),
        source_format="jsonl",
        row_count=0,
    )
    dataset.synthetic_version_id = version.id
    return dataset


def _dataset_of(repo, version_id: uuid.UUID, kind: str):
    return next(
        (dataset for dataset in repo.datasets_for_version(version_id) if dataset.kind == kind),
        None,
    )


# ── Profiles ───────────────────────────────────────────────────────────────


@router.get("/profiles", response_model=list[ProfileRead])
async def list_profiles(request: Request) -> list[ProfileRead]:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        return [_profile_to_read(repo, profile) for profile in repo.list_profiles()]


@router.post("/profiles", response_model=ProfileRead, status_code=201)
async def create_profile(request: Request, body: ProfileCreate) -> ProfileRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    name = body.name.strip()
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        if not name or repo.get_profile_by_name(name):
            raise _error(
                409, "PROFILE_NAME_TAKEN", f"A synthetic profile named '{name}' already exists."
            )

    product = await _knowledge_product(settings, body.knowledge_product_id)
    collection, product_name = _vector_collection(product)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        if repo.get_profile_by_name(name):
            raise _error(
                409, "PROFILE_NAME_TAKEN", f"A synthetic profile named '{name}' already exists."
            )
        profile = repo.create_profile(
            name=name,
            description=(body.description or "").strip() or None,
            knowledge_product_id=body.knowledge_product_id,
            knowledge_product_name=product_name or None,
            qdrant_collection=collection,
        )
        db.commit()
        return _profile_to_read(repo, profile)


@router.get("/profiles/{profile_id}", response_model=ProfileDetailRead)
async def get_profile(request: Request, profile_id: uuid.UUID) -> ProfileDetailRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = repo.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Synthetic profile not found.")
        return ProfileDetailRead(
            profile=_profile_to_read(repo, profile),
            versions=[_version_to_read(repo, version) for version in repo.list_versions(profile_id)],
        )


@router.patch("/profiles/{profile_id}", response_model=ProfileRead)
async def update_profile(
    request: Request, profile_id: uuid.UUID, body: ProfileUpdate
) -> ProfileRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = repo.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Synthetic profile not found.")
        if body.name is not None:
            name = body.name.strip()
            other = repo.get_profile_by_name(name) if name else None
            if not name or (other and other.id != profile.id):
                raise _error(
                    409, "PROFILE_NAME_TAKEN", f"A synthetic profile named '{name}' already exists."
                )
            profile.name = name
        if body.description is not None:
            profile.description = body.description.strip() or None
        db.commit()
        return _profile_to_read(repo, profile)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(request: Request, profile_id: uuid.UUID) -> None:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = repo.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Synthetic profile not found.")
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
async def create_version(
    request: Request, profile_id: uuid.UUID, body: VersionCreate
) -> VersionRead:
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    kinds, config = _version_config(body)
    _check_model(settings)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        profile = repo.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Synthetic profile not found.")

        if body.fabric_profile_id is not None:
            fabric = DatasetProfileRepository(db).get(body.fabric_profile_id)
            if not fabric:
                raise _error(422, "FABRIC_PROFILE_MISMATCH", "No such Dataset Fabric profile.")
            if (fabric.knowledge_product_id or "") != profile.knowledge_product_id:
                raise _error(
                    422,
                    "FABRIC_PROFILE_MISMATCH",
                    "The Dataset Fabric profile belongs to a different Knowledge Product.",
                )

        if body.version_no is not None and any(
            version.version_no == body.version_no for version in repo.list_versions(profile_id)
        ):
            raise _error(409, "VERSION_NO_TAKEN", f"Version {body.version_no} already exists.")

        version_no = body.version_no or repo.next_version_no(profile_id)
        version = repo.create_version(
            profile_id=profile_id,
            version_no=version_no,
            description=(body.description or "").strip() or None,
            status="queued",
            config=config,
            progress={
                "kinds": {
                    kind: {"status": "queued", "rows": 0, "rows_target": 0} for kind in kinds
                }
            },
            fabric_profile_id=body.fabric_profile_id,
        )

        for kind in kinds:
            _create_dataset_row(eval_repo, settings, profile, version, kind, config[KIND_CONFIG_KEY[kind]])

        db.commit()
        version_uuid = version.id
        _enqueue(request, version_uuid, kinds)
        return _version_to_read(repo, repo.get_version(version_uuid))


@router.get("/versions/{version_id}", response_model=VersionRead)
async def get_version(request: Request, version_id: uuid.UUID) -> VersionRead:
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        return _version_to_read(repo, version)


# ── The datasets of one version ────────────────────────────────────────────


@router.post("/versions/{version_id}/datasets", response_model=VersionRead, status_code=201)
async def add_version_dataset(
    request: Request, version_id: uuid.UUID, body: DatasetCreate
) -> VersionRead:
    """Add the kind this version does not have yet, and generate it."""
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    _check_model(settings)
    _validate_kind_config(body.kind, body.config)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        if _dataset_of(repo, version_id, body.kind):
            raise _error(
                409,
                "DATASET_EXISTS",
                f"This version already has a {KIND_WORD[body.kind]}-turn dataset.",
            )
        profile = repo.get_profile(version.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Synthetic profile not found.")

        config = dict(version.config or {})
        config[KIND_CONFIG_KEY[body.kind]] = body.config.model_dump(mode="json")
        _create_dataset_row(
            eval_repo, settings, profile, version, body.kind, config[KIND_CONFIG_KEY[body.kind]]
        )
        progress = dict(version.progress or {})
        progress["kinds"] = {
            **(progress.get("kinds") or {}),
            body.kind: {"status": "queued", "rows": 0, "rows_target": body.config.rows},
        }
        repo.update_version(version_id, config=config, progress=progress, status="queued")
        db.commit()
        _enqueue(request, version_id, [body.kind])
        return _version_to_read(repo, repo.get_version(version_id))


@router.patch("/versions/{version_id}/datasets/{kind}", response_model=VersionRead)
async def update_version_dataset(
    request: Request, version_id: uuid.UUID, kind: DatasetKind, body: DatasetUpdate
) -> VersionRead:
    """Save the configuration without generating. Used by the Edit button."""
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    _validate_kind_config(kind, body.config)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        if not _dataset_of(repo, version_id, kind):
            raise _error(404, "DATASET_NOT_FOUND", "This version has no such dataset.")

        config = dict(version.config or {})
        config[KIND_CONFIG_KEY[kind]] = body.config.model_dump(mode="json")
        repo.update_version(version_id, config=config)
        db.commit()
        return _version_to_read(repo, repo.get_version(version_id))


@router.post("/versions/{version_id}/datasets/{kind}/regenerate", response_model=VersionRead)
async def regenerate_version_dataset(
    request: Request,
    version_id: uuid.UUID,
    kind: DatasetKind,
    body: DatasetUpdate | None = Body(default=None),
) -> VersionRead:
    """Replace this dataset's rows with a fresh run, optionally with a new configuration."""
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    _check_model(settings)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        dataset = _dataset_of(repo, version_id, kind)
        if not dataset:
            raise _error(404, "DATASET_NOT_FOUND", "This version has no such dataset.")

        config = dict(version.config or {})
        if body is not None:
            _validate_kind_config(kind, body.config)
            config[KIND_CONFIG_KEY[kind]] = body.config.model_dump(mode="json")

        progress = dict(version.progress or {})
        progress["kinds"] = {
            **(progress.get("kinds") or {}),
            kind: {
                "status": "queued",
                "rows": 0,
                "rows_target": (config.get(KIND_CONFIG_KEY[kind]) or {}).get("rows", 0),
            },
        }
        repo.update_version(
            version_id,
            config=config,
            progress=progress,
            status="queued",
            error_message=None,
            completed_at=None,
        )
        db.commit()
        _enqueue(request, version_id, [kind])
        return _version_to_read(repo, repo.get_version(version_id))


@router.delete("/versions/{version_id}/datasets/{kind}", status_code=204)
async def delete_version_dataset(
    request: Request, version_id: uuid.UUID, kind: DatasetKind
) -> None:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    stored: list[tuple[str, str]] = []
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        dataset = _dataset_of(repo, version_id, kind)
        if not dataset:
            raise _error(404, "DATASET_NOT_FOUND", "This version has no such dataset.")
        if dataset.storage_bucket and dataset.storage_key:
            stored.append((dataset.storage_bucket, dataset.storage_key))
        dataset_id = dataset.id
        EvaluationRepository(db).delete_dataset(dataset_id)

        config = dict(version.config or {})
        config.pop(KIND_CONFIG_KEY[kind], None)
        progress = dict(version.progress or {})
        kinds_progress = dict(progress.get("kinds") or {})
        kinds_progress.pop(kind, None)
        progress["kinds"] = kinds_progress
        row_field = "row_count_single" if kind == "single_turn" else "row_count_multi"
        repo.update_version(version_id, config=config, progress=progress, **{row_field: 0})
        db.commit()

    for bucket, key in stored:
        try:
            await delete_stored_file(settings, bucket=bucket, key=key)
        except DatasetStorageError as exc:
            logger.warning("synthetic dataset object delete failed key=%s error=%s", key, exc)


@router.get("/versions/{version_id}/items", response_model=VersionItemsRead)
async def list_version_items(
    request: Request,
    version_id: uuid.UUID,
    kind: DatasetKind = "single_turn",
    offset: int = 0,
    limit: int = 20,
) -> VersionItemsRead:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
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


@router.delete("/versions/{version_id}", status_code=204)
async def delete_version(request: Request, version_id: uuid.UUID) -> None:
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Synthetic version not found.")
        stored = [
            (dataset.storage_bucket, dataset.storage_key)
            for dataset in repo.datasets_for_version(version_id)
            if dataset.storage_bucket and dataset.storage_key
        ]
        for dataset in repo.datasets_for_version(version_id):
            eval_repo.delete_dataset(dataset.id)
        repo.delete_version(version_id)
        db.commit()

    for bucket, key in stored:
        try:
            await delete_stored_file(settings, bucket=bucket, key=key)
        except DatasetStorageError as exc:
            logger.warning("synthetic dataset object delete failed key=%s error=%s", key, exc)
