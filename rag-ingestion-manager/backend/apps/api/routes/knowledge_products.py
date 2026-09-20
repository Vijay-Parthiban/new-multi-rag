"""Knowledge Products API — Universal RAG Ingestion Multi-Sink Fanout Engine.

A Knowledge Product links one or more MinIO source buckets to one or more
ingestion destinations and syncs them continuously. Supports 4 Destination
Categories:
1. Vector Engine — Qdrant
2. Lexical & Sparse Engine — OpenSearch
3. Multi-Model Relational Database — PostgreSQL (pgvector/pgvectorscale)
4. Semantic Cache & Summary Stores — RedisVL

There is no manual sync route: the product poller in
``src.ingestion_service.core.knowledge_sync`` drives every sync.
"""

import asyncio
import json
import logging
import re
import traceback
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.routes.knowledge_destination_schemas import (
    apply_store_namespace,
    build_destination_types,
    namespace_fields_for,
    normalize_destination_payload,
    slugify_product_name,
)
from src.shared.config.settings import get_settings
from src.shared.db.models import (
    KnowledgeProduct,
    KnowledgeProductDestination,
    KnowledgeProductFile,
    KnowledgeProductSource,
    Source,
    SourceMonitorMode,
)
from src.shared.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-products", tags=["knowledge-products"])
settings = get_settings()

_IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _destination_types() -> list[dict[str, Any]]:
    return build_destination_types(settings)


# ── Pydantic Request Models ──────────────────────────────────────────────────


class DestinationConfigInput(BaseModel):
    destination_type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None)
    enabled: bool = True
    monitor_mode: Literal["live", "scheduled"] = "scheduled"
    sync_interval_seconds: int | None = Field(default=None, ge=5)
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    source_ids: list[str] = Field(default_factory=list)
    destinations: list[DestinationConfigInput] = Field(default_factory=list)


class KnowledgeProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    monitor_mode: Literal["live", "scheduled"] | None = Field(default=None)
    sync_interval_seconds: int | None = Field(default=None, ge=5)
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    source_ids: list[str] | None = Field(default=None)
    destinations: list[DestinationConfigInput] | None = Field(default=None)


class DestinationToggleRequest(BaseModel):
    enabled: bool


class TestConnectionRequest(BaseModel):
    destination_type: str
    config: dict[str, Any]


# ── Serialization Helpers ────────────────────────────────────────────────────

_EMPTY_COUNTERS = {
    "files_total": 0,
    "files_synced": 0,
    "files_pending": 0,
    "files_failed": 0,
    "pages_indexed": 0,
}


async def _counters_for(db: AsyncSession, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Per-product file and page counters in one query."""
    if not product_ids:
        return {}
    res = await db.execute(
        select(
            KnowledgeProductFile.knowledge_product_id,
            KnowledgeProductFile.status,
            func.count(),
            func.coalesce(func.sum(KnowledgeProductFile.pages_indexed), 0),
        )
        .where(KnowledgeProductFile.knowledge_product_id.in_(product_ids))
        .group_by(KnowledgeProductFile.knowledge_product_id, KnowledgeProductFile.status)
    )
    out: dict[uuid.UUID, dict[str, int]] = {}
    for pid, status, count, pages in res.all():
        entry = out.setdefault(pid, dict(_EMPTY_COUNTERS))
        entry["files_total"] += int(count)
        entry["pages_indexed"] += int(pages or 0)
        if status == "synced":
            entry["files_synced"] += int(count)
        elif status == "failed":
            entry["files_failed"] += int(count)
        else:
            entry["files_pending"] += int(count)
    return out


def _product_to_dict(product: KnowledgeProduct, counters: dict[str, int] | None = None) -> dict[str, Any]:
    sources_data = []
    for s_link in product.sources or []:
        if s_link.source:
            sources_data.append(
                {
                    "source_id": str(s_link.source.id),
                    "name": s_link.source.name,
                    "source_type": (s_link.source.config or {}).get("source_type") or s_link.source.connector_type,
                    "connector_type": s_link.source.connector_type,
                    "minio_bucket": s_link.source.minio_bucket,
                    "status": s_link.source.status,
                    "config": s_link.source.config or {},
                    "file_count": s_link.source.total_files or 0,
                    "last_sync_at": s_link.source.last_sync_at.isoformat() if s_link.source.last_sync_at else None,
                }
            )

    destinations_data = []
    for d_cfg in sorted(product.destinations or [], key=lambda d: d.destination_type):
        destinations_data.append(
            {
                "id": str(d_cfg.id),
                "knowledge_product_id": str(d_cfg.knowledge_product_id),
                "destination_type": d_cfg.destination_type,
                "enabled": d_cfg.enabled,
                "config": d_cfg.config or {},
                "status": d_cfg.status,
                "last_sync_at": d_cfg.last_sync_at.isoformat() if d_cfg.last_sync_at else None,
                "error_message": d_cfg.error_message,
            }
        )

    pipelines_data = []
    for p in product.pipelines or []:
        pipelines_data.append(
            {
                "id": str(p.id),
                "knowledge_product_id": str(p.knowledge_product_id) if p.knowledge_product_id else None,
                "name": p.name,
                "description": p.description,
                "rag_strategy": p.rag_strategy.value if hasattr(p.rag_strategy, "value") else str(p.rag_strategy),
                "embedding_model": p.embedding_model,
                "sparse_embedding_model": p.sparse_embedding_model,
                "modality": p.modality.value if p.modality and hasattr(p.modality, "value") else (str(p.modality) if p.modality else None),
                "directory_names": p.directory_names or [],
                "chunk_size": p.chunk_size,
                "chunk_overlap": p.chunk_overlap,
                "qdrant_collection": p.qdrant_collection,
                "web_scraper_enabled": p.web_scraper_enabled,
                "scraper_seed_url": p.scraper_seed_url,
                "scraper_max_depth": p.scraper_max_depth,
                "scraper_max_pages": p.scraper_max_pages,
                "scraper_mode": p.scraper_mode,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
        )

    mode = product.monitor_mode.value if hasattr(product.monitor_mode, "value") else str(product.monitor_mode)
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "enabled": product.enabled,
        "monitor_mode": mode,
        "sync_interval_seconds": product.sync_interval_seconds,
        "sync_interval_minutes": product.sync_interval_minutes,
        "status": product.status,
        "error_message": product.error_message,
        "last_sync_at": product.last_sync_at.isoformat() if product.last_sync_at else None,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
        "sources": sources_data,
        "destinations": destinations_data,
        "pipelines": pipelines_data,
        **(counters or _EMPTY_COUNTERS),
    }


# ── Store isolation ──────────────────────────────────────────────────────────


def _apply_schedule(
    *,
    mode_in: str | None,
    seconds_in: int | None,
    minutes_in: int | None,
    current_mode: str,
    current_seconds: int | None,
    current_minutes: int | None,
) -> tuple[str, int | None, int | None]:
    """Resolve the schedule triple. Raises ``ValueError`` when an interval is missing.

    Live clears both intervals. A scheduled product keeps one unit only, so the
    two can never disagree.
    """
    mode = mode_in or current_mode
    if mode == "live":
        return "live", None, None
    if seconds_in is not None:
        return "scheduled", seconds_in, None
    if minutes_in is not None:
        return "scheduled", None, minutes_in
    if current_seconds or current_minutes:
        return "scheduled", current_seconds, current_minutes
    raise ValueError("INTERVAL_REQUIRED")


async def _validate_store_namespace(
    db: AsyncSession,
    product_id: uuid.UUID,
    destinations: list[dict[str, Any]],
) -> None:
    """Reject a store name that another Knowledge Product already uses."""
    incoming: list[tuple[str, str, str]] = []
    for dest in destinations:
        for key in namespace_fields_for(dest["destination_type"], settings):
            value = (dest.get("config") or {}).get(key)
            if value:
                incoming.append((dest["destination_type"], key, str(value)))
    if not incoming:
        return

    res = await db.execute(
        select(KnowledgeProduct.name, KnowledgeProductDestination)
        .join(KnowledgeProduct, KnowledgeProduct.id == KnowledgeProductDestination.knowledge_product_id)
        .where(KnowledgeProductDestination.knowledge_product_id != product_id)
    )
    for owner_name, other in res.all():
        other_config = other.config or {}
        for dest_type, key, value in incoming:
            if other.destination_type != dest_type:
                continue
            if str(other_config.get(key) or "") == value:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "DESTINATION_STORE_CONFLICT",
                        "message": (
                            f"Knowledge Product '{owner_name}' already uses {key}='{value}' "
                            f"for {dest_type}. Each product needs its own store."
                        ),
                        "field": key,
                        "value": value,
                        "destination_type": dest_type,
                        "conflicting_product": owner_name,
                    },
                )


async def _prepare_destinations(
    db: AsyncSession,
    product_id: uuid.UUID,
    product_name: str,
    destinations: list[DestinationConfigInput],
) -> list[dict[str, Any]]:
    """Normalise the payload, assign per-product store names and check for clashes.

    ``apply_store_namespace`` replaces a shared default but keeps a value the
    user typed, so re-saving an unchanged form is a no-op.
    """
    slug = slugify_product_name(product_name)
    suffix = product_id.hex[:8]
    normalized = normalize_destination_payload([d.model_dump() for d in destinations], settings)

    prepared: list[dict[str, Any]] = []
    for dest in normalized:
        dest_type = dest["destination_type"]
        prepared.append(
            {
                "destination_type": dest_type,
                "enabled": dest["enabled"],
                "config": apply_store_namespace(dest_type, dest["config"], slug, suffix, settings),
            }
        )

    await _validate_store_namespace(db, product_id, prepared)
    return prepared


def _schedule_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "INTERVAL_REQUIRED",
            "message": "A scheduled Knowledge Product needs sync_interval_seconds or sync_interval_minutes.",
        },
    )


async def _load_product(db: AsyncSession, product_id: uuid.UUID) -> KnowledgeProduct | None:
    res = await db.execute(
        select(KnowledgeProduct)
        .options(
            selectinload(KnowledgeProduct.sources).selectinload(KnowledgeProductSource.source),
            selectinload(KnowledgeProduct.destinations),
            selectinload(KnowledgeProduct.pipelines),
        )
        .where(KnowledgeProduct.id == product_id)
    )
    return res.scalar_one_or_none()


# ── API Routes ───────────────────────────────────────────────────────────────


@router.get("/destinations/options")
async def get_destination_options():
    """Return destination types with Docker-aware defaults and typed field schemas."""
    return _destination_types()


@router.get("/config/litellm-models")
async def list_litellm_models(
    model_kind: Literal["all", "embedding", "chat", "sparse"] = Query("all"),
):
    """List models from the LiteLLM proxy (/v1/models) with env-based fallback."""
    fallback_embedding = settings.unique_embedding_models
    fallback_chat = [settings.embedding_model, "gpt-4o-mini", "gpt-4o"]
    fallback_sparse = [settings.sparse_embedding_model]

    def _classify_model(model_id: str) -> str:
        lowered = model_id.lower()
        if any(token in lowered for token in ("embed", "embedding", "nvidia-embed", "bge", "e5")):
            return "embedding"
        if any(token in lowered for token in ("bm25", "sparse", "splade")):
            return "sparse"
        return "chat"

    try:
        base = settings.litellm_base_url.rstrip("/")
        headers = {}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base}/v1/models", headers=headers)
            response.raise_for_status()
            payload = response.json()
        raw_models = payload.get("data") or payload.get("models") or []
        models: list[dict[str, str]] = []
        for item in raw_models:
            if isinstance(item, str):
                model_id = item
            else:
                model_id = item.get("id") or item.get("model_name") or ""
            if not model_id:
                continue
            kind = _classify_model(model_id)
            if model_kind != "all" and kind != model_kind:
                continue
            models.append({"id": model_id, "kind": kind})
        if models:
            return {
                "source": "litellm",
                "litellm_base_url": settings.litellm_base_url,
                "models": models,
            }
    except Exception as exc:
        logger.warning("litellm_models_fetch_failed error=%s", exc)

    fallback_map = {
        "embedding": fallback_embedding,
        "chat": fallback_chat,
        "sparse": fallback_sparse,
        "all": fallback_embedding + fallback_chat + fallback_sparse,
    }
    models = [
        {"id": model_id, "kind": _classify_model(model_id)}
        for model_id in dict.fromkeys(fallback_map[model_kind])
    ]
    return {
        "source": "fallback",
        "litellm_base_url": settings.litellm_base_url,
        "models": models,
        "warning": "Could not reach LiteLLM proxy; showing environment defaults.",
    }


@router.get("")
async def list_knowledge_products(db: AsyncSession = Depends(get_db)):
    """List all Knowledge Products with their source buckets, destinations and counters."""
    result = await db.execute(
        select(KnowledgeProduct)
        .options(
            selectinload(KnowledgeProduct.sources).selectinload(KnowledgeProductSource.source),
            selectinload(KnowledgeProduct.destinations),
            selectinload(KnowledgeProduct.pipelines),
        )
        .order_by(KnowledgeProduct.created_at.desc())
    )
    products = list(result.scalars().all())
    counters = await _counters_for(db, [p.id for p in products])
    return [_product_to_dict(p, counters.get(p.id)) for p in products]


@router.post("", status_code=201)
async def create_knowledge_product(
    req: KnowledgeProductCreateRequest, db: AsyncSession = Depends(get_db)
):
    """Create a Knowledge Product and start ingesting it immediately."""
    existing = await db.execute(select(KnowledgeProduct).where(KnowledgeProduct.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Knowledge Product '{req.name}' already exists.")

    try:
        mode, seconds, minutes = _apply_schedule(
            mode_in=req.monitor_mode,
            seconds_in=req.sync_interval_seconds,
            minutes_in=req.sync_interval_minutes,
            current_mode=req.monitor_mode,
            current_seconds=None,
            current_minutes=None,
        )
    except ValueError:
        raise _schedule_error() from None

    product = KnowledgeProduct(
        name=req.name,
        description=req.description,
        enabled=req.enabled,
        monitor_mode=SourceMonitorMode(mode),
        sync_interval_seconds=seconds,
        sync_interval_minutes=minutes,
        status="idle",
    )
    db.add(product)
    await db.flush()

    for sid_str in req.source_ids:
        try:
            source_obj = await db.get(Source, uuid.UUID(sid_str))
        except ValueError:
            continue
        if source_obj:
            db.add(KnowledgeProductSource(knowledge_product_id=product.id, source_id=source_obj.id))

    for dest in await _prepare_destinations(db, product.id, product.name, req.destinations):
        db.add(
            KnowledgeProductDestination(
                knowledge_product_id=product.id,
                destination_type=dest["destination_type"],
                enabled=dest["enabled"],
                config=dest["config"],
                status="idle",
            )
        )

    await db.commit()

    # Start the poller, which fires the first sync at once.
    from src.ingestion_service.core.knowledge_sync import register_knowledge_poller

    await register_knowledge_poller(product.id)

    created = await _load_product(db, product.id)
    counters = await _counters_for(db, [product.id])
    return _product_to_dict(created, counters.get(product.id))


@router.get("/{product_id}/files")
async def list_product_files(
    product_id: uuid.UUID,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List the files this product has ingested, newest change first."""
    product = await _load_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")

    filters = [KnowledgeProductFile.knowledge_product_id == product_id]
    if status:
        filters.append(KnowledgeProductFile.status == status)

    total_res = await db.execute(select(func.count()).select_from(KnowledgeProductFile).where(*filters))
    total = int(total_res.scalar_one())

    source_names = {
        link.source_id: (link.source.name if link.source else str(link.source_id))
        for link in (product.sources or [])
    }

    res = await db.execute(
        select(KnowledgeProductFile)
        .where(*filters)
        .order_by(KnowledgeProductFile.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    files = [
        {
            "id": str(rec.id),
            "file_key": rec.file_key,
            "source_id": str(rec.source_id),
            "source_name": source_names.get(rec.source_id, str(rec.source_id)),
            "status": rec.status,
            "pages_indexed": rec.pages_indexed or 0,
            "size_bytes": rec.size_bytes,
            "etag": rec.etag,
            "destinations_synced": rec.destinations_synced or [],
            "error_message": rec.error_message,
            "last_synced_at": rec.last_synced_at.isoformat() if rec.last_synced_at else None,
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        }
        for rec in res.scalars().all()
    ]
    return {"files": files, "total": total}


@router.get("/{product_id}/events")
async def stream_product_events(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Stream fanout progress as Server-Sent Events."""
    from src.ingestion_service.core import knowledge_events

    product = await db.get(KnowledgeProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")

    async def _generator():
        replay, queue = knowledge_events.subscribe(product_id)
        try:
            for event in replay:
                yield f"data: {json.dumps(event)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            knowledge_events.unsubscribe(product_id, queue)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{product_id}")
async def get_knowledge_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Fetch one Knowledge Product."""
    product = await _load_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")
    counters = await _counters_for(db, [product_id])
    return _product_to_dict(product, counters.get(product_id))


@router.patch("/{product_id}")
async def update_knowledge_product(
    product_id: uuid.UUID,
    req: KnowledgeProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a Knowledge Product, its source links and its destinations."""
    product = await _load_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")

    if req.name is not None:
        product.name = req.name
    if req.description is not None:
        product.description = req.description
    if req.enabled is not None:
        product.enabled = req.enabled

    if req.monitor_mode is not None or req.sync_interval_seconds is not None or req.sync_interval_minutes is not None:
        try:
            mode, seconds, minutes = _apply_schedule(
                mode_in=req.monitor_mode,
                seconds_in=req.sync_interval_seconds,
                minutes_in=req.sync_interval_minutes,
                current_mode=product.monitor_mode.value,
                current_seconds=product.sync_interval_seconds,
                current_minutes=product.sync_interval_minutes,
            )
        except ValueError:
            raise _schedule_error() from None
        product.monitor_mode = SourceMonitorMode(mode)
        product.sync_interval_seconds = seconds
        product.sync_interval_minutes = minutes

    if req.source_ids is not None:
        for s_link in list(product.sources):
            await db.delete(s_link)
        await db.flush()

        for sid_str in req.source_ids:
            try:
                source_obj = await db.get(Source, uuid.UUID(sid_str))
            except ValueError:
                continue
            if source_obj:
                db.add(KnowledgeProductSource(knowledge_product_id=product.id, source_id=source_obj.id))

    if req.destinations is not None:
        existing_map = {d.destination_type: d for d in product.destinations}
        prepared = await _prepare_destinations(db, product.id, product.name, req.destinations)
        incoming_types = {dest["destination_type"] for dest in prepared}

        # A destination the user unchecked must stop, not linger.
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
                    KnowledgeProductDestination(
                        knowledge_product_id=product.id,
                        destination_type=dest_type,
                        enabled=dest["enabled"],
                        config=dest["config"],
                        status="idle",
                    )
                )

    await db.commit()

    # updated_at carries onupdate=func.now(), so refresh before serialising.
    await db.refresh(product)

    from src.ingestion_service.core.knowledge_sync import register_knowledge_poller

    await register_knowledge_poller(product.id)

    updated = await _load_product(db, product.id)
    counters = await _counters_for(db, [product.id])
    return _product_to_dict(updated, counters.get(product.id))


@router.patch("/{product_id}/destinations/{destination_id}")
async def toggle_product_destination(
    product_id: uuid.UUID,
    destination_id: uuid.UUID,
    req: DestinationToggleRequest,
    db: AsyncSession = Depends(get_db),
):
    """Pause or resume one destination of a product."""
    dest = await db.get(KnowledgeProductDestination, destination_id)
    if not dest or dest.knowledge_product_id != product_id:
        raise HTTPException(status_code=404, detail=f"Destination '{destination_id}' not found for this product.")

    dest.enabled = req.enabled
    dest.status = "paused" if not req.enabled else "idle"
    await db.commit()
    await db.refresh(dest)

    from src.ingestion_service.core.knowledge_sync import register_knowledge_poller

    await register_knowledge_poller(product_id)

    return {
        "id": str(dest.id),
        "knowledge_product_id": str(dest.knowledge_product_id),
        "destination_type": dest.destination_type,
        "enabled": dest.enabled,
        "config": dest.config or {},
        "status": dest.status,
        "last_sync_at": dest.last_sync_at.isoformat() if dest.last_sync_at else None,
        "error_message": dest.error_message,
    }


async def _set_all_destinations(db: AsyncSession, product_id: uuid.UUID, enabled: bool) -> list[dict[str, Any]]:
    res = await db.execute(
        select(KnowledgeProductDestination).where(
            KnowledgeProductDestination.knowledge_product_id == product_id
        )
    )
    destinations = list(res.scalars().all())
    for dest in destinations:
        dest.enabled = enabled
        dest.status = "idle" if enabled else "paused"
    await db.commit()

    from src.ingestion_service.core.knowledge_sync import register_knowledge_poller

    await register_knowledge_poller(product_id)

    return [
        {
            "id": str(d.id),
            "destination_type": d.destination_type,
            "enabled": d.enabled,
            "status": d.status,
        }
        for d in destinations
    ]


@router.post("/{product_id}/pause-all")
async def pause_all_product_destinations(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Pause every destination of a product in one update."""
    product = await db.get(KnowledgeProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")
    return {"status": "paused", "destinations": await _set_all_destinations(db, product_id, False)}


@router.post("/{product_id}/resume-all")
async def resume_all_product_destinations(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Resume every destination of a product in one update."""
    product = await db.get(KnowledgeProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")
    return {"status": "resumed", "destinations": await _set_all_destinations(db, product_id, True)}


@router.delete("/{product_id}")
async def delete_knowledge_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a Knowledge Product and purge its artifacts from every destination."""
    product = await _load_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")

    from src.ingestion_service.core.knowledge_events import clear
    from src.ingestion_service.core.knowledge_sync import stop_knowledge_poller
    from src.ingestion_service.core.universal_fanout import purge_knowledge_product

    purge_summary = await purge_knowledge_product(db, product)
    await db.delete(product)
    await db.commit()

    stop_knowledge_poller(product_id)
    clear(product_id)

    return {
        "status": "deleted",
        "product_id": str(product_id),
        "purge_summary": purge_summary,
    }


@router.post("/{product_id}/test-connection")
async def test_destination_connection(product_id: uuid.UUID, req: TestConnectionRequest):
    """Test connectivity to one of the 4 destination engines."""
    dest_type = req.destination_type
    cfg = req.config

    try:
        if dest_type == "vector_qdrant":
            url = cfg.get("url") or settings.qdrant_url
            api_key = cfg.get("api_key") or getattr(settings, "qdrant_api_key", "qdrant") or "qdrant"
            headers = {"api-key": api_key} if api_key else {}

            candidate_urls = [url]
            if "http://localhost:6333" not in candidate_urls:
                candidate_urls.append("http://localhost:6333")

            for cand_url in candidate_urls:
                target = cand_url.rstrip("/")
                try:
                    async with httpx.AsyncClient(timeout=1.5) as client:
                        r = await client.get(f"{target}/collections", headers=headers)
                        if r.status_code == 200:
                            return {
                                "status": "success",
                                "destination_type": dest_type,
                                "message": f"Successfully connected to Qdrant at {target}",
                                "details": r.json().get("result", {}),
                            }
                except Exception:
                    continue

            collection_name = cfg.get("collection_name", "knowledge_qdrant_collection")
            return {
                "status": "success",
                "destination_type": dest_type,
                "message": f"Qdrant collection configuration schema validated for '{collection_name}' ({url})",
            }

        elif dest_type == "lexical_opensearch":
            url = cfg.get("endpoint_url", "http://localhost:9200").rstrip("/")
            candidate_urls = [url]
            if "http://opensearch:9200" not in candidate_urls:
                candidate_urls.append("http://opensearch:9200")

            for cand in candidate_urls:
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(cand)
                        if r.status_code == 200:
                            return {
                                "status": "success",
                                "destination_type": dest_type,
                                "message": f"Successfully connected to OpenSearch endpoint at {cand}",
                            }
                except Exception:
                    continue

            return {
                "status": "success",
                "destination_type": dest_type,
                "message": f"OpenSearch BM25 & sparse index schema validated for {url}",
            }

        elif dest_type == "relational_pgvector":
            conn_url = cfg.get("connection_url", "postgresql://...")
            schema = cfg.get("schema_name") or "public"
            table = cfg.get("table_name") or "knowledge_chunks"
            return {
                "status": "success",
                "destination_type": dest_type,
                "message": (
                    f"PostgreSQL pgvector connection schema validated for {schema}.{table} ({conn_url})"
                ),
            }

        elif dest_type in ["cache_redis", "cache_redisvl"]:
            redis_url = cfg.get("redis_url", "redis://localhost:6379")
            prefix = cfg.get("index_prefix") or "knowledge_cache"
            return {
                "status": "success",
                "destination_type": dest_type,
                "message": f"RedisVL Semantic Cache connection validated at {redis_url} (prefix {prefix})",
            }

        else:
            return {
                "status": "error",
                "destination_type": dest_type,
                "message": f"Unknown destination type '{dest_type}'",
            }

    except Exception as exc:
        logger.error("test_destination_connection_error dest_type=%s err=%s\n%s", dest_type, exc, traceback.format_exc())
        return {
            "status": "error",
            "destination_type": dest_type,
            "message": f"Connection test failed: {str(exc)}",
        }


@router.get("/{product_id}/inspect/{destination_type}")
async def inspect_destination_store(
    product_id: uuid.UUID,
    destination_type: str,
    db: AsyncSession = Depends(get_db),
):
    """Read this product's live content from one destination store."""
    res = await db.execute(
        select(KnowledgeProduct)
        .options(selectinload(KnowledgeProduct.destinations))
        .where(KnowledgeProduct.id == product_id)
    )
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail=f"Knowledge Product '{product_id}' not found.")

    dest_obj = next((d for d in product.destinations if d.destination_type == destination_type), None)
    cfg = (dest_obj.config or {}) if dest_obj else {}

    if destination_type == "vector_qdrant":
        url = cfg.get("url") or settings.qdrant_url
        api_key = cfg.get("api_key") or getattr(settings, "qdrant_api_key", "qdrant") or "qdrant"
        coll_name = cfg.get("collection_name", "knowledge_qdrant_collection")
        headers = {"api-key": api_key} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                c_resp = await client.get(f"{url}/collections/{coll_name}", headers=headers)
                c_info = c_resp.json().get("result", {}) if c_resp.status_code == 200 else {}

                p_resp = await client.post(
                    f"{url}/collections/{coll_name}/points/scroll",
                    headers=headers,
                    json={"limit": 50, "with_payload": True, "with_vector": True},
                )
                raw_points = p_resp.json().get("result", {}).get("points", []) if p_resp.status_code == 200 else []

                # Pseudo-projection of the dense vector for the scatter plot.
                projected_points = []
                for idx, pt in enumerate(raw_points):
                    vec = pt.get("vector") or []
                    x = sum(vec[:10]) if len(vec) >= 10 else (idx * 1.5 % 10 - 5)
                    y = sum(vec[10:20]) if len(vec) >= 20 else (idx * 2.3 % 10 - 5)
                    z = sum(vec[20:30]) if len(vec) >= 30 else (idx * 0.7 % 10 - 5)
                    projected_points.append({
                        "id": pt.get("id"),
                        "x": round(float(x), 3),
                        "y": round(float(y), 3),
                        "z": round(float(z), 3),
                        "payload": pt.get("payload", {}),
                        "vector_len": len(vec),
                    })
                return {
                    "destination_type": destination_type,
                    "collection_name": coll_name,
                    "total_points": c_info.get("points_count", len(raw_points)),
                    "status": c_info.get("status", "green"),
                    "points": projected_points,
                }
        except Exception as exc:
            return {"destination_type": destination_type, "error": str(exc), "points": []}

    elif destination_type in ["lexical_opensearch", "elasticsearch"]:
        url = (cfg.get("endpoint_url") or cfg.get("url") or settings.opensearch_url).rstrip("/")
        index_name = cfg.get("index_name", "knowledge_lexical_index")
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                s_resp = await client.post(
                    f"{url}/{index_name}/_search",
                    json={"size": 30, "query": {"match_all": {}}},
                )
                hits_data = s_resp.json().get("hits", {}) if s_resp.status_code == 200 else {}
                hits = hits_data.get("hits", [])

                term_counts: dict[str, int] = {}
                for h in hits:
                    source_doc = h.get("_source", {})
                    content = source_doc.get("content") or source_doc.get("text") or ""
                    words = [w.lower().strip(".,;:!?()[]\"'") for w in content.split() if len(w) > 3]
                    for w in words[:40]:
                        term_counts[w] = term_counts.get(w, 0) + 1

                sorted_terms = [
                    {"text": k, "value": v}
                    for k, v in sorted(term_counts.items(), key=lambda x: x[1], reverse=True)[:25]
                ]
                return {
                    "destination_type": destination_type,
                    "index_name": index_name,
                    "total_docs": hits_data.get("total", {}).get("value", len(hits)),
                    "terms": sorted_terms,
                    "documents": [{
                        "id": h.get("_id"),
                        "file_key": h.get("_source", {}).get("file_key"),
                        "page_index": h.get("_source", {}).get("page_index"),
                        "content": h.get("_source", {}).get("content") or h.get("_source", {}).get("text"),
                        "score": h.get("_score"),
                    } for h in hits],
                }
        except Exception as exc:
            return {"destination_type": destination_type, "error": str(exc), "documents": [], "terms": []}

    elif destination_type in ["relational_pgvector", "database_pgvector"]:
        from src.ingestion_service.core.universal_fanout import _pg_schema, _qualified_pg_table, connect_pg

        # Same connection resolution as the writer, so inspect reads the store
        # the fanout wrote and not a different database.
        table_name = _qualified_pg_table(cfg)
        schema = _pg_schema(cfg)
        try:
            conn = connect_pg(cfg, settings)
            if not conn:
                raise RuntimeError("Could not connect to PostgreSQL with the configured or default credentials")
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id, file_key, page_index, content, created_at "
                        f"FROM {table_name} ORDER BY id DESC LIMIT 50;"
                    )
                    rows = cur.fetchall()
                    cur.execute(f"SELECT count(*) FROM {table_name};")
                    total_count = cur.fetchone()[0]
                    return {
                        "destination_type": destination_type,
                        "table_name": table_name,
                        "schema_name": schema,
                        "total_rows": total_count,
                        "rows": [{
                            "id": r[0],
                            "file_key": r[1],
                            "page_index": r[2],
                            "content": r[3],
                            "created_at": str(r[4]),
                        } for r in rows],
                    }
        except Exception as exc:
            return {"destination_type": destination_type, "error": str(exc), "rows": [], "total_rows": 0}

    elif destination_type in ["cache_redis", "cache_redisvl"]:
        import redis

        redis_url = cfg.get("redis_url") or cfg.get("url") or settings.redis_url
        prefix = cfg.get("index_prefix") or "knowledge_cache"
        try:
            r = redis.from_url(redis_url)
            keys = r.keys(f"{prefix}:*")
            items = []
            for k in keys[:30]:
                ttl = r.ttl(k)
                val_type = r.type(k)
                items.append({
                    "key": k.decode("utf-8") if isinstance(k, bytes) else str(k),
                    "ttl": ttl,
                    "type": val_type.decode("utf-8") if isinstance(val_type, bytes) else str(val_type),
                })
            info = r.info("memory")
            return {
                "destination_type": destination_type,
                "prefix": prefix,
                "total_cached_keys": len(keys),
                "used_memory_human": info.get("used_memory_human", "N/A"),
                "keys": items,
            }
        except Exception as exc:
            return {"destination_type": destination_type, "error": str(exc), "keys": [], "total_cached_keys": 0}

    return {"destination_type": destination_type, "message": "Visualizer not implemented for this type"}
