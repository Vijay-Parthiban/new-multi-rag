"""Ingestion Profiles API — reusable destination and chunking configuration.

An Ingestion Profile holds the destination connection and index settings plus the
chunking parameters. A Knowledge Product copies the destinations into its own
rows when it is created, so editing a profile here never changes a product that
already exists; ``POST /api/knowledge-products/{id}/apply-profile`` re-copies on
demand.

Store names are NOT assigned here. A profile keeps the catalogue defaults, and
the product copy rewrites them to ``kp_<slug>_<id8>``, because two products
sharing one profile still need separate stores.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.routes.knowledge_destination_schemas import normalize_destination_payload
from src.shared.config.settings import get_settings
from src.shared.db.models import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    DEFAULT_IMAGE_MIN_PIXELS,
    DEFAULT_MODALITY_MODE,
    ChunkStrategy,
    IngestionModality,
    IngestionProfile,
    IngestionProfileDestination,
    KnowledgeProduct,
)
from src.shared.db.session import get_db

router = APIRouter(prefix="/api/ingestion-profiles", tags=["ingestion-profiles"])
settings = get_settings()


# ── Pydantic Request Models ──────────────────────────────────────────────────


class IngestionProfileDestinationInput(BaseModel):
    destination_type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


# The stored column is the ChunkStrategy enum. The API takes the same seven names
# as a Literal, so a bad value is a 422 at the edge and never reaches the column.
ChunkStrategyName = Literal[
    "recursive",
    "fixed",
    "sentence",
    "section",
    "layout",
    "context_aware",
    "parent_child",
]


class IngestionProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None)
    enabled: bool = True
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=100, le=8000)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=2000)
    chunk_strategy: ChunkStrategyName = DEFAULT_CHUNK_STRATEGY
    modality_mode: Literal["text", "text_images"] = DEFAULT_MODALITY_MODE
    text_embedding_model: str = Field(
        default=settings.embedding_model, min_length=1, max_length=128
    )
    caption_model: str | None = Field(default=settings.caption_model, max_length=128)
    image_min_pixels: int = Field(default=DEFAULT_IMAGE_MIN_PIXELS, ge=0)
    destinations: list[IngestionProfileDestinationInput] = Field(default_factory=list)


class IngestionProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    chunk_strategy: ChunkStrategyName | None = Field(default=None)
    modality_mode: Literal["text", "text_images"] | None = Field(default=None)
    text_embedding_model: str | None = Field(default=None, min_length=1, max_length=128)
    caption_model: str | None = Field(default=None, max_length=128)
    image_min_pixels: int | None = Field(default=None, ge=0)
    destinations: list[IngestionProfileDestinationInput] | None = Field(default=None)


# ── Serialization Helpers ────────────────────────────────────────────────────


def _profile_to_dict(profile: IngestionProfile, product_count: int = 0) -> dict[str, Any]:
    destinations_data = []
    for dest in sorted(profile.destinations or [], key=lambda d: d.destination_type):
        destinations_data.append(
            {
                "id": str(dest.id),
                "ingestion_profile_id": str(dest.ingestion_profile_id),
                "destination_type": dest.destination_type,
                "enabled": dest.enabled,
                "config": dest.config or {},
                "created_at": dest.created_at.isoformat() if dest.created_at else None,
                "updated_at": dest.updated_at.isoformat() if dest.updated_at else None,
            }
        )

    return {
        "id": str(profile.id),
        "name": profile.name,
        "description": profile.description,
        "enabled": profile.enabled,
        "chunk_size": profile.chunk_size,
        "chunk_overlap": profile.chunk_overlap,
        "chunk_strategy": (
            profile.chunk_strategy.value
            if hasattr(profile.chunk_strategy, "value")
            else str(profile.chunk_strategy or DEFAULT_CHUNK_STRATEGY)
        ),
        "modality_mode": (
            profile.modality_mode.value
            if hasattr(profile.modality_mode, "value")
            else str(profile.modality_mode or DEFAULT_MODALITY_MODE)
        ),
        "text_embedding_model": profile.text_embedding_model,
        "caption_model": profile.caption_model,
        "image_min_pixels": profile.image_min_pixels,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "product_count": product_count,
        "destinations": destinations_data,
    }


async def _product_counts_for(
    db: AsyncSession, profile_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """How many Knowledge Products reference each profile, in one query."""
    if not profile_ids:
        return {}
    res = await db.execute(
        select(KnowledgeProduct.ingestion_profile_id, func.count())
        .where(KnowledgeProduct.ingestion_profile_id.in_(profile_ids))
        .group_by(KnowledgeProduct.ingestion_profile_id)
    )
    return {pid: int(count) for pid, count in res.all() if pid is not None}


# ── Validation Helpers ───────────────────────────────────────────────────────


def _chunk_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "CHUNK_OVERLAP_TOO_LARGE",
            "message": "Chunk overlap must be smaller than the chunk size.",
        },
    )


def _validate_chunking(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise _chunk_error()


def _validate_modality(
    modality_mode: str, caption_model: str | None, effective_caption: str | None
) -> None:
    """Reject an images profile with no caption model, at save time.

    The fanout falls back to the environment caption model, so this is not a
    crash guard: it tells the user now instead of silently captioning with a
    different model.
    """
    if modality_mode == "text_images" and not (caption_model or effective_caption):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CAPTION_MODEL_REQUIRED",
                "message": "modality_mode 'text_images' needs a caption_model.",
            },
        )


def _normalize_profile_destinations(
    destinations: list[IngestionProfileDestinationInput],
) -> list[dict[str, Any]]:
    """Merge the catalogue defaults in and drop unknown destination types."""
    return normalize_destination_payload([d.model_dump() for d in destinations], settings)


async def _load_profile(db: AsyncSession, profile_id: uuid.UUID) -> IngestionProfile:
    res = await db.execute(
        select(IngestionProfile)
        .options(selectinload(IngestionProfile.destinations))
        .where(IngestionProfile.id == profile_id)
        # populate_existing: this helper is called straight after a commit that
        # deleted destination rows. Without it the identity map hands back the
        # collection it loaded before the delete, so the response shows rows that
        # are gone.
        .execution_options(populate_existing=True)
    )
    profile = res.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"Ingestion Profile '{profile_id}' not found."
        )
    return profile


async def _references_for(db: AsyncSession, profile_id: uuid.UUID) -> int:
    res = await db.execute(
        select(func.count()).where(KnowledgeProduct.ingestion_profile_id == profile_id)
    )
    return int(res.scalar_one() or 0)


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("")
async def list_ingestion_profiles(db: AsyncSession = Depends(get_db)):
    """List every Ingestion Profile with its destinations and usage count."""
    result = await db.execute(
        select(IngestionProfile)
        .options(selectinload(IngestionProfile.destinations))
        .order_by(IngestionProfile.created_at.desc())
    )
    profiles = list(result.scalars().all())
    counts = await _product_counts_for(db, [p.id for p in profiles])
    return [_profile_to_dict(p, counts.get(p.id, 0)) for p in profiles]


@router.post("", status_code=201)
async def create_ingestion_profile(
    req: IngestionProfileCreateRequest, db: AsyncSession = Depends(get_db)
):
    """Create an Ingestion Profile."""
    existing = await db.execute(select(IngestionProfile).where(IngestionProfile.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400, detail=f"Ingestion Profile '{req.name}' already exists."
        )

    _validate_chunking(req.chunk_size, req.chunk_overlap)
    _validate_modality(req.modality_mode, req.caption_model, None)

    profile = IngestionProfile(
        name=req.name,
        description=req.description,
        enabled=req.enabled,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
        chunk_strategy=ChunkStrategy(req.chunk_strategy),
        modality_mode=IngestionModality(req.modality_mode),
        text_embedding_model=req.text_embedding_model,
        caption_model=req.caption_model or None,
        image_min_pixels=req.image_min_pixels,
    )
    db.add(profile)
    await db.flush()

    for dest in _normalize_profile_destinations(req.destinations):
        db.add(
            IngestionProfileDestination(
                ingestion_profile_id=profile.id,
                destination_type=dest["destination_type"],
                enabled=dest["enabled"],
                config=dest["config"],
            )
        )

    await db.commit()

    created = await _load_profile(db, profile.id)
    return _profile_to_dict(created)


@router.get("/{profile_id}")
async def get_ingestion_profile(profile_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Fetch one Ingestion Profile."""
    profile = await _load_profile(db, profile_id)
    return _profile_to_dict(profile, await _references_for(db, profile_id))


@router.patch("/{profile_id}")
async def update_ingestion_profile(
    profile_id: uuid.UUID,
    req: IngestionProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an Ingestion Profile. Supplied destinations replace the whole set."""
    profile = await _load_profile(db, profile_id)

    if req.name is not None and req.name != profile.name:
        clash = await db.execute(
            select(IngestionProfile).where(
                IngestionProfile.name == req.name, IngestionProfile.id != profile_id
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail=f"Ingestion Profile '{req.name}' already exists."
            )
        profile.name = req.name
    if req.description is not None:
        profile.description = req.description
    if req.enabled is not None:
        profile.enabled = req.enabled

    # Validate the effective pair, so a PATCH that sends only one half is still checked.
    next_size = req.chunk_size if req.chunk_size is not None else profile.chunk_size
    next_overlap = req.chunk_overlap if req.chunk_overlap is not None else profile.chunk_overlap
    _validate_chunking(next_size, next_overlap)
    profile.chunk_size = next_size
    profile.chunk_overlap = next_overlap

    if req.chunk_strategy is not None:
        profile.chunk_strategy = ChunkStrategy(req.chunk_strategy)

    # Validate the effective modality pair, so a PATCH that switches to images
    # without sending a caption model is still checked against the stored one.
    current_mode = (
        profile.modality_mode.value
        if hasattr(profile.modality_mode, "value")
        else str(profile.modality_mode or DEFAULT_MODALITY_MODE)
    )
    next_mode = req.modality_mode if req.modality_mode is not None else current_mode
    _validate_modality(next_mode, req.caption_model, profile.caption_model)
    profile.modality_mode = IngestionModality(next_mode)
    if req.text_embedding_model is not None:
        profile.text_embedding_model = req.text_embedding_model
    if req.caption_model is not None:
        profile.caption_model = req.caption_model or None
    if req.image_min_pixels is not None:
        profile.image_min_pixels = req.image_min_pixels

    if req.destinations is not None:
        existing_map = {d.destination_type: d for d in profile.destinations}
        prepared = _normalize_profile_destinations(req.destinations)
        incoming_types = {dest["destination_type"] for dest in prepared}

        for dest_type, d_obj in existing_map.items():
            if dest_type not in incoming_types:
                await db.delete(d_obj)

        for dest in prepared:
            dest_type = dest["destination_type"]
            if dest_type in existing_map:
                d_obj = existing_map[dest_type]
                d_obj.enabled = dest["enabled"]
                d_obj.config = dest["config"]
            else:
                db.add(
                    IngestionProfileDestination(
                        ingestion_profile_id=profile.id,
                        destination_type=dest_type,
                        enabled=dest["enabled"],
                        config=dest["config"],
                    )
                )

    await db.commit()

    updated = await _load_profile(db, profile.id)
    return _profile_to_dict(updated, await _references_for(db, profile_id))


@router.delete("/{profile_id}")
async def delete_ingestion_profile(profile_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete an Ingestion Profile that no Knowledge Product references."""
    profile = await _load_profile(db, profile_id)

    count = await _references_for(db, profile_id)
    if count:
        # The FK is SET NULL, so deleting would leave every referencing product
        # with copied destination rows and no way to reach the profile again.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROFILE_IN_USE",
                "message": (
                    f"Ingestion Profile '{profile.name}' is used by {count} Knowledge "
                    "Product(s). Detach or delete them first."
                ),
                "product_count": count,
            },
        )

    await db.delete(profile)
    await db.commit()
    return {"status": "deleted", "profile_id": str(profile_id)}
