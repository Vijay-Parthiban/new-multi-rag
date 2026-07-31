"""Sources API — CRUD for external data sources backed by Airbyte/Pathway connectors."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.shared.db.models import (
    Pipeline,
    PipelineSource,
    Source,
    SourceMonitorMode,
)
from src.shared.db.session import get_db
from src.shared.storage import ensure_bucket
from src.shared.config.settings import get_settings

router = APIRouter(prefix="/api/sources", tags=["sources"])

CONNECTOR_OPTIONS = [
    {"id": "google_drive", "label": "Google Drive", "description": "Sync files from Google Drive"},
    {"id": "gcs", "label": "Google Cloud Storage", "description": "Sync files from GCS buckets"},
    {"id": "s3", "label": "Amazon S3", "description": "Sync files from S3 buckets"},
    {"id": "azure_blob", "label": "Azure Blob Storage", "description": "Sync files from Azure Blob"},
    {"id": "onedrive", "label": "OneDrive", "description": "Sync files from OneDrive"},
    {"id": "dropbox", "label": "Dropbox", "description": "Sync files from Dropbox"},
    {"id": "postgres", "label": "PostgreSQL", "description": "Sync data from PostgreSQL tables"},
    {"id": "mysql", "label": "MySQL", "description": "Sync data from MySQL tables"},
    {"id": "mongodb", "label": "MongoDB", "description": "Sync documents from MongoDB collections"},
    {"id": "github", "label": "GitHub", "description": "Sync from GitHub repositories"},
    {"id": "slack", "label": "Slack", "description": "Sync messages from Slack channels"},
    {"id": "confluence", "label": "Confluence", "description": "Sync pages from Confluence"},
    {"id": "sharepoint", "label": "SharePoint", "description": "Sync files from SharePoint"},
    {"id": "sftp", "label": "SFTP", "description": "Sync files via SFTP"},
    {"id": "http_api", "label": "HTTP API", "description": "Sync data from REST APIs"},
]


class SourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    connector_type: str = Field(min_length=1, max_length=64)
    config: dict = Field(default_factory=dict)
    monitor_mode: Literal["live", "scheduled"] = "live"
    sync_interval_minutes: int | None = Field(default=None, ge=1)


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict | None = None
    monitor_mode: Literal["live", "scheduled"] | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


async def _source_to_dict(s: Source) -> dict:
    await s.awaitable_attrs.pipelines
    await s.awaitable_attrs.created_at
    await s.awaitable_attrs.updated_at
    if s.last_sync_at:
        await s.awaitable_attrs.last_sync_at
    return {
        "id": str(s.id),
        "name": s.name,
        "connector_type": s.connector_type,
        "config": s.config or {},
        "monitor_mode": s.monitor_mode.value,
        "minio_bucket": s.minio_bucket,
        "sync_interval_minutes": s.sync_interval_minutes,
        "enabled": s.enabled,
        "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
        "status": s.status,
        "error_message": s.error_message,
        "pipeline_ids": [
            str(ps.pipeline_id) for ps in (s.pipelines or [])
        ],
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _make_bucket_name(source_id: str, name: str) -> str:
    """Generate a deterministic MinIO bucket name for a source."""
    settings = get_settings()
    safe_name = name.lower().replace(" ", "-").replace("_", "-")
    short_id = source_id[:8]
    return f"{settings.minio_bucket_prefix}-{safe_name}-{short_id}"


@router.get("/connectors", status_code=200)
async def list_connectors():
    """Return available Airbyte connector types."""
    return {"connectors": CONNECTOR_OPTIONS}


@router.get("", status_code=200)
async def list_sources(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(Source).order_by(Source.created_at.desc()))
    return [await _source_to_dict(s) for s in result.scalars().all()]


@router.post("", status_code=201)
async def create_source(
    body: SourceCreateRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create a new external data source with its own MinIO bucket."""
    # Validate connector type
    valid_ids = {c["id"] for c in CONNECTOR_OPTIONS}
    if body.connector_type not in valid_ids:
        raise ValidationError(
            "INVALID_CONNECTOR",
            f"Unknown connector type. Valid options: {sorted(valid_ids)}",
        )

    # Check name uniqueness
    existing = await db.execute(select(Source).where(Source.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise ConflictError(
            "SOURCE_EXISTS",
            f"A source named '{body.name}' already exists.",
        )

    # Generate UUID client-side so we can compute bucket name before INSERT
    source_id = uuid.uuid4()
    bucket = _make_bucket_name(str(source_id), body.name.strip())

    source = Source(
        id=source_id,
        name=body.name.strip(),
        connector_type=body.connector_type,
        config=body.config,
        monitor_mode=SourceMonitorMode(body.monitor_mode),
        minio_bucket=bucket,
        sync_interval_minutes=body.sync_interval_minutes,
    )
    db.add(source)
    await db.commit()
    source = await db.get(Source, source.id)

    # Create MinIO bucket asynchronously (fire-and-forget is fine, will retry on use)
    try:
        await ensure_bucket(bucket)
    except Exception:
        # Bucket creation is best-effort; the pathway worker will retry
        pass

    # Trigger initial sync if source is enabled (fire-and-forget)
    if source.enabled:
        try:
            from src.ingestion_service.clients.source_sync import trigger_source_sync as do_sync
            await do_sync(db, source.id)
        except Exception:
            pass

    return await _source_to_dict(source)


@router.get("/{source_id}", status_code=200)
async def get_source(source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")
    return await _source_to_dict(source)


@router.patch("/{source_id}", status_code=200)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    if body.name is not None:
        existing = await db.execute(
            select(Source).where(Source.name == body.name.strip(), Source.id != source_id)
        )
        if existing.scalar_one_or_none():
            raise ConflictError("NAME_IN_USE", "Another source already uses this name.")
        source.name = body.name.strip()
    if body.config is not None:
        source.config = body.config
    if body.monitor_mode is not None:
        source.monitor_mode = SourceMonitorMode(body.monitor_mode)
    if body.sync_interval_minutes is not None:
        source.sync_interval_minutes = body.sync_interval_minutes
    if body.enabled is not None:
        source.enabled = body.enabled

    await db.commit()
    source = await db.get(Source, source.id)
    return await _source_to_dict(source)


@router.delete("/{source_id}", status_code=200)
async def delete_source(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    # Check if any pipelines are still linked
    if source.pipelines:
        linked = [str(ps.pipeline_id) for ps in source.pipelines]
        raise ConflictError(
            "SOURCE_IN_USE",
            f"Source is still linked to {len(linked)} pipeline(s). Remove links first.",
            {"pipeline_ids": linked},
        )

    # Remove bucket from MinIO (best-effort)
    try:
        from src.shared.storage import delete_bucket as s3_delete_bucket
        await s3_delete_bucket(source.minio_bucket)
    except Exception:
        pass

    await db.delete(source)
    await db.commit()
    return {"status": "deleted", "id": str(source_id)}


@router.post("/{source_id}/pipeline/{pipeline_id}", status_code=200)
async def link_source_to_pipeline(
    source_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Link a source to a pipeline."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("Source_NIT_FOUND", "Source not found.")
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    existing = await db.execute(
        select(PipelineSource).where(
            PipelineSource.source_id == source_id,
            PipelineSource.pipeline_id == pipeline_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("LINK_EXISTS", "This source is already linked to this pipeline.")

    link = PipelineSource(source_id=source_id, pipeline_id=pipeline_id)
    db.add(link)
    await db.commit()
    return {"status": "linked", "source_id": str(source_id), "pipeline_id": str(pipeline_id)}


@router.delete("/{source_id}/pipeline/{pipeline_id}", status_code=200)
async def unlink_source_from_pipeline(
    source_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a source-pipeline link."""
    existing = await db.execute(
        select(PipelineSource).where(
            PipelineSource.source_id == source_id,
            PipelineSource.pipeline_id == pipeline_id,
        )
    )
    link = existing.scalar_one_or_none()
    if not link:
        raise NotFoundError("LINK_NOT_FOUND", "This source is not linked to this pipeline.")
    await db.delete(link)
    await db.commit()
    return {"status": "unlinked", "source_id": str(source_id), "pipeline_id": str(pipeline_id)}


@router.get("/{source_id}/files", status_code=200)
async def list_source_files(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    prefix: str = Query(default=""),
):
    """List files in the source's MinIO bucket."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("Source_NOT_FOUND", "Source not found.")

    from src.shared.storage import list_objects as s3_list

    files = await s3_list(source.minio_bucket, prefix=prefix)
    return {
        "source_id": str(source_id),
        "bucket": source.minio_bucket,
        "files": [
            {
                "key": f.key,
                "size": f.size,
                "last_modified": f.last_modified,
            }
            for f in files
        ],
    }


@router.post("/{source_id}/sync", status_code=200)
async def trigger_source_sync(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually trigger a sync for a source via the Pathway Airbyte worker."""
    from src.ingestion_service.clients.source_sync import trigger_source_sync as do_sync
    return await do_sync(db, source_id)