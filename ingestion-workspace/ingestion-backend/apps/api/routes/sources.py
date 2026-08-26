"""Sources API — CRUD for external data sources backed by Airbyte/Pathway connectors.

Each source is a MinIO bucket that can have multiple Airbyte connectors feeding into it.
Two monitoring modes at two points:
  - Connectors → Source: how connectors sync into the bucket (per-connector)
  - Source → Pipeline: how bucket changes trigger pipeline re-indexing (per-link or source default)
"""

import logging
import uuid
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.shared.db.session import get_db
from src.shared.storage import ensure_bucket
from src.shared.db.models import Source, SourceConnector, SourceMonitorMode, Pipeline, PipelineSource
from src.shared.config.settings import get_settings

router = APIRouter(prefix="/api/sources", tags=["sources"])
settings = get_settings()

CONNECTOR_OPTIONS = [
    {"id": "google_drive", "label": "Google Drive", "description": "Sync files from Google Drive"},
    {"id": "google_sheets", "label": "Google Sheets", "description": "Sync spreadsheets from Google Sheets"},
    {"id": "gcs", "label": "Google Cloud Storage", "description": "Sync files from GCS buckets"},
    {"id": "s3", "label": "Amazon S3", "description": "Sync files from S3 buckets"},
    {"id": "azure_blob", "label": "Azure Blob Storage", "description": "Sync files from Azure Blob"},
    {"id": "azure", "label": "Azure Blob Storage", "description": "Sync files from Azure Blob"},
    {"id": "onedrive", "label": "OneDrive", "description": "Sync files from OneDrive"},
    {"id": "microsoft_onedrive", "label": "OneDrive", "description": "Sync files from Microsoft OneDrive"},
    {"id": "sharepoint", "label": "SharePoint", "description": "Sync files from SharePoint"},
    {"id": "dropbox", "label": "Dropbox", "description": "Sync files from Dropbox"},
    {"id": "postgres", "label": "PostgreSQL", "description": "Sync data from PostgreSQL tables"},
    {"id": "mysql", "label": "MySQL", "description": "Sync data from MySQL tables"},
    {"id": "mongodb", "label": "MongoDB", "description": "Sync documents from MongoDB collections"},
    {"id": "github", "label": "GitHub", "description": "Sync from GitHub repositories"},
    {"id": "slack", "label": "Slack", "description": "Sync messages from Slack channels"},
    {"id": "confluence", "label": "Confluence", "description": "Sync pages from Confluence"},
    {"id": "sftp", "label": "SFTP", "description": "Sync files via SFTP"},
    {"id": "http_api", "label": "HTTP API", "description": "Sync data from REST APIs"},
]

VALID_CONNECTOR_IDS = {c["id"] for c in CONNECTOR_OPTIONS}


# ── Pydantic request models ──────────────────────────────────────────────


class ConnectorCreateRequest(BaseModel):
    connector_type: str = Field(min_length=1, max_length=64)
    config: dict = Field(default_factory=dict)
    monitor_mode: Literal["live", "scheduled"] = "live"
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool = True


class ConnectorUpdateRequest(BaseModel):
    config: dict | None = None
    monitor_mode: Literal["live", "scheduled"] | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class SourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    # Legacy single-connector fields (backward compat)
    connector_type: str | None = Field(default=None, max_length=64)
    config: dict = Field(default_factory=dict)
    # Multi-connector: initial connectors to add
    connectors: list[ConnectorCreateRequest] = Field(default_factory=list)
    # Source-level monitoring defaults
    connector_monitor_mode: Literal["live", "scheduled"] = "live"
    connector_sync_interval_minutes: int | None = Field(default=None, ge=1)
    pipeline_monitor_mode: Literal["live", "scheduled"] = "live"
    pipeline_sync_interval_minutes: int | None = Field(default=None, ge=1)
    # Legacy compat
    monitor_mode: Literal["live", "scheduled"] = "live"
    sync_interval_minutes: int | None = Field(default=None, ge=1)


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict | None = None
    connector_monitor_mode: Literal["live", "scheduled"] | None = None
    connector_sync_interval_minutes: int | None = Field(default=None, ge=1)
    pipeline_monitor_mode: Literal["live", "scheduled"] | None = None
    pipeline_sync_interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    # Legacy compat
    monitor_mode: Literal["live", "scheduled"] | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1)


class LinkPipelineRequest(BaseModel):
    monitor_mode: Literal["live", "scheduled"] | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1)


# ── Serialization helpers ─────────────────────────────────────────────────


def _connector_to_dict(c: SourceConnector) -> dict:
    return {
        "id": str(c.id),
        "source_id": str(c.source_id),
        "connector_type": c.connector_type,
        "config": c.config or {},
        "monitor_mode": c.monitor_mode.value if c.monitor_mode else "live",
        "sync_interval_minutes": c.sync_interval_minutes,
        "enabled": c.enabled,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "status": c.status,
        "error_message": c.error_message,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


async def _source_to_dict(s: Source) -> dict:
    await s.awaitable_attrs.pipelines
    await s.awaitable_attrs.connectors
    await s.awaitable_attrs.created_at
    await s.awaitable_attrs.updated_at
    if s.last_sync_at:
        await s.awaitable_attrs.last_sync_at
    return {
        "id": str(s.id),
        "name": s.name,
        # Legacy fields
        "connector_type": s.connector_type,
        "config": s.config or {},
        "monitor_mode": s.connector_monitor_mode.value if s.connector_monitor_mode else "live",
        # New multi-connector fields
        "connector_monitor_mode": s.connector_monitor_mode.value if s.connector_monitor_mode else "live",
        "connector_sync_interval_minutes": s.connector_sync_interval_minutes,
        "pipeline_monitor_mode": s.pipeline_monitor_mode.value if s.pipeline_monitor_mode else "live",
        "pipeline_sync_interval_minutes": s.pipeline_sync_interval_minutes,
        "minio_bucket": s.minio_bucket,
        "sync_interval_minutes": s.sync_interval_minutes,
        "enabled": s.enabled,
        "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
        "status": s.status,
        "error_message": s.error_message,
        "pipeline_ids": [str(ps.pipeline_id) for ps in (s.pipelines or [])],
        "pipeline_links": [
            {
                "pipeline_id": str(ps.pipeline_id),
                "monitor_mode": ps.monitor_mode.value if ps.monitor_mode else None,
                "sync_interval_minutes": ps.sync_interval_minutes,
            }
            for ps in (s.pipelines or [])
        ],
        "connectors": [_connector_to_dict(c) for c in (s.connectors or [])],
        "connector_count": len(s.connectors or []),
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _make_bucket_name(source_id: str, name: str) -> str:
    """Generate a deterministic MinIO bucket name for a source."""
    safe_name = name.lower().replace(" ", "-").replace("_", "-")
    short_id = source_id[:8]
    return f"{settings.minio_bucket_prefix}-{safe_name}-{short_id}"


# ── Connector catalog ────────────────────────────────────────────────────


@router.get("/connectors", status_code=200)
async def list_connectors():
    """Return available Airbyte connector types."""
    return {"connectors": CONNECTOR_OPTIONS}


# ── Source CRUD ───────────────────────────────────────────────────────────


@router.get("", status_code=200)
async def list_sources(db: Annotated[AsyncSession, Depends(get_db)]):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.pipelines), selectinload(Source.connectors))
        .order_by(Source.created_at.desc())
    )
    return [await _source_to_dict(s) for s in result.scalars().all()]

@router.post("", status_code=201)
async def create_source(
    body: SourceCreateRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create a new external data source with its own MinIO bucket.

    Supports both legacy single-connector and new multi-connector creation:
    - Legacy: pass connector_type + config directly
    - New: pass connectors[] array with multiple connector configs
    """
    # Build connector list from either legacy or new format
    connector_requests: list[ConnectorCreateRequest] = []
    if body.connectors:
        connector_requests = body.connectors
    elif body.connector_type:
        connector_requests = [
            ConnectorCreateRequest(
                connector_type=body.connector_type,
                config=body.config,
                monitor_mode=body.monitor_mode,
                sync_interval_minutes=body.sync_interval_minutes,
            )
        ]

    # Validate connector types
    for cr in connector_requests:
        if cr.connector_type not in VALID_CONNECTOR_IDS:
            raise ValidationError(
                "INVALID_CONNECTOR",
                f"Unknown connector type '{cr.connector_type}'. "
                f"Valid options: {sorted(VALID_CONNECTOR_IDS)}",
            )

    # Check name uniqueness
    existing = await db.execute(select(Source).where(Source.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise ConflictError("SOURCE_EXISTS", f"A source named '{body.name}' already exists.")

    source_id = uuid.uuid4()
    bucket = _make_bucket_name(str(source_id), body.name.strip())

    source = Source(
        id=source_id,
        name=body.name.strip(),
        connector_type=body.connector_type,
        config=body.config,
        connector_monitor_mode=SourceMonitorMode(body.connector_monitor_mode),
        connector_sync_interval_minutes=body.connector_sync_interval_minutes,
        pipeline_monitor_mode=SourceMonitorMode(body.pipeline_monitor_mode),
        pipeline_sync_interval_minutes=body.pipeline_sync_interval_minutes,
        minio_bucket=bucket,
        sync_interval_minutes=body.sync_interval_minutes,
    )
    db.add(source)

    # Add connectors
    for cr in connector_requests:
        connector = SourceConnector(
            source_id=source_id,
            connector_type=cr.connector_type,
            config=cr.config,
            monitor_mode=SourceMonitorMode(cr.monitor_mode),
            sync_interval_minutes=cr.sync_interval_minutes,
            enabled=cr.enabled,
        )
        db.add(connector)

    await db.commit()
    source = await db.get(Source, source.id)

    # Create MinIO bucket
    try:
        await ensure_bucket(bucket)
    except Exception:
        pass

    # Set up bucket notifications for live monitoring mode
    if source.pipeline_monitor_mode == SourceMonitorMode.LIVE:
        try:
            from src.shared.storage.s3_client import setup_bucket_notification
            webhook_url = f"{settings.internal_api_url}/api/sources/{source.id}/events"
            await setup_bucket_notification(bucket, webhook_url)
        except Exception as exc:
            logger.warning(
                "bucket_notification_setup_failed source=%s bucket=%s error=%s",
                source.id, bucket, exc,
            )

    # Trigger initial sync for all connectors
    if source.enabled and connector_requests:
        try:
            from src.ingestion_service.clients.source_sync import trigger_source_sync as do_sync
            await do_sync(db, source.id)
        except Exception:
            pass

    return await _source_to_dict(source)


@router.get("/{source_id}", status_code=200)
async def get_source(source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.pipelines), selectinload(Source.connectors))
        .where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
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

    old_pipeline_mode = source.pipeline_monitor_mode

    # Handle legacy monitor_mode field
    if body.monitor_mode is not None and body.connector_monitor_mode is None:
        body.connector_monitor_mode = body.monitor_mode
    if body.sync_interval_minutes is not None and body.connector_sync_interval_minutes is None:
        body.connector_sync_interval_minutes = body.sync_interval_minutes

    if body.connector_monitor_mode is not None:
        source.connector_monitor_mode = SourceMonitorMode(body.connector_monitor_mode)
    if body.connector_sync_interval_minutes is not None:
        source.connector_sync_interval_minutes = body.connector_sync_interval_minutes
    if body.pipeline_monitor_mode is not None:
        source.pipeline_monitor_mode = SourceMonitorMode(body.pipeline_monitor_mode)
    if body.pipeline_sync_interval_minutes is not None:
        source.pipeline_sync_interval_minutes = body.pipeline_sync_interval_minutes
    if body.enabled is not None:
        source.enabled = body.enabled

    await db.commit()

    # Handle pipeline monitor mode changes (bucket notifications)
    if body.pipeline_monitor_mode is not None and old_pipeline_mode != source.pipeline_monitor_mode:
        try:
            from src.shared.storage.s3_client import setup_bucket_notification
            if source.pipeline_monitor_mode == SourceMonitorMode.LIVE:
                webhook_url = f"{settings.internal_api_url}/api/sources/{source.id}/events"
                await setup_bucket_notification(source.minio_bucket, webhook_url)
                logger.info("bucket_notification_enabled source=%s", source.id)
            else:
                logger.info("monitor_mode_changed_to_scheduled source=%s", source.id)
        except Exception as exc:
            logger.warning("bucket_notification_update_failed source=%s error=%s", source.id, exc)

    source = await db.get(Source, source.id)
    return await _source_to_dict(source)


@router.delete("/{source_id}", status_code=200)
async def delete_source(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

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


# ── Source Connectors CRUD ────────────────────────────────────────────────


@router.get("/{source_id}/connectors", status_code=200)
async def list_source_connectors(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    """List all connectors for a source."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")
    result = await db.execute(
        select(SourceConnector)
        .where(SourceConnector.source_id == source_id)
        .order_by(SourceConnector.created_at.desc())
    )
    return [_connector_to_dict(c) for c in result.scalars().all()]


@router.post("/{source_id}/connectors", status_code=201)
async def add_source_connector(
    source_id: uuid.UUID,
    body: ConnectorCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a new connector to an existing source."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    if body.connector_type not in VALID_CONNECTOR_IDS:
        raise ValidationError(
            "INVALID_CONNECTOR",
            f"Unknown connector type '{body.connector_type}'. "
            f"Valid options: {sorted(VALID_CONNECTOR_IDS)}",
        )

    connector = SourceConnector(
        source_id=source_id,
        connector_type=body.connector_type,
        config=body.config,
        monitor_mode=SourceMonitorMode(body.monitor_mode),
        sync_interval_minutes=body.sync_interval_minutes,
        enabled=body.enabled,
    )
    db.add(connector)
    await db.commit()

    connector = await db.get(SourceConnector, connector.id)

    # Trigger initial sync if enabled
    if connector.enabled:
        try:
            from src.shared.queue.client import enqueue_pathway_sync
            await enqueue_pathway_sync(source_id)
        except Exception:
            pass

    return _connector_to_dict(connector)


@router.get("/{source_id}/connectors/{connector_id}", status_code=200)
async def get_source_connector(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a specific connector."""
    connector = await db.get(SourceConnector, connector_id)
    if not connector or connector.source_id != source_id:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found.")
    return _connector_to_dict(connector)


@router.patch("/{source_id}/connectors/{connector_id}", status_code=200)
async def update_source_connector(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    body: ConnectorUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a connector's config, monitor mode, or enabled status."""
    connector = await db.get(SourceConnector, connector_id)
    if not connector or connector.source_id != source_id:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found.")

    if body.config is not None:
        connector.config = body.config
    if body.monitor_mode is not None:
        connector.monitor_mode = SourceMonitorMode(body.monitor_mode)
    if body.sync_interval_minutes is not None:
        connector.sync_interval_minutes = body.sync_interval_minutes
    if body.enabled is not None:
        connector.enabled = body.enabled

    await db.commit()
    connector = await db.get(SourceConnector, connector_id)
    return _connector_to_dict(connector)


@router.delete("/{source_id}/connectors/{connector_id}", status_code=200)
async def delete_source_connector(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a connector from a source."""
    connector = await db.get(SourceConnector, connector_id)
    if not connector or connector.source_id != source_id:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found.")

    await db.delete(connector)
    await db.commit()
    return {"status": "deleted", "connector_id": str(connector_id), "source_id": str(source_id)}


@router.post("/{source_id}/connectors/{connector_id}/sync", status_code=200)
async def trigger_connector_sync(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually trigger sync for a specific connector."""
    connector = await db.get(SourceConnector, connector_id)
    if not connector or connector.source_id != source_id:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found.")

    if not connector.enabled:
        return {"status": "error", "message": "Connector is disabled"}

    connector.status = "syncing"
    connector.error_message = None
    await db.commit()

    from src.shared.queue.client import enqueue_pathway_sync
    await enqueue_pathway_sync(source_id)

    return {
        "status": "triggered",
        "connector_id": str(connector_id),
        "source_id": str(source_id),
        "connector_type": connector.connector_type,
    }


# ── Pipeline linking ──────────────────────────────────────────────────────


@router.post("/{source_id}/pipeline/{pipeline_id}", status_code=200)
async def link_source_to_pipeline(
    source_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: LinkPipelineRequest | None = None,
):
    """Link a source to a pipeline with optional per-link monitoring config."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")
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

    link = PipelineSource(
        source_id=source_id,
        pipeline_id=pipeline_id,
        monitor_mode=SourceMonitorMode(body.monitor_mode) if body and body.monitor_mode else None,
        sync_interval_minutes=body.sync_interval_minutes if body else None,
    )
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


# ── Source files ──────────────────────────────────────────────────────────


@router.get("/{source_id}/files", status_code=200)
async def list_source_files(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    prefix: str = Query(default=""),
):
    """List files in the source's MinIO bucket."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

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
@router.post("/{source_id}/files", status_code=201)
async def upload_source_file(
    source_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Upload a file directly into the source's MinIO bucket.

    Multipart field name must be `file`. In live monitoring mode, the bucket
    notification webhook fires and triggers pipeline re-indexing automatically.
    """
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    form = await request.form()
    upload = form.get("file")
    if upload is None or getattr(upload, "filename", None) is None:
        raise ValidationError("FILE_REQUIRED", "Multipart field 'file' is required.")

    data = await upload.read()
    if not data:
        raise ValidationError("EMPTY_FILE", "Uploaded file is empty.")

    key = upload.filename.strip("/")
    from src.shared.storage import ensure_bucket, put_object

    await ensure_bucket(source.minio_bucket)
    await put_object(source.minio_bucket, key, data)
    logger.info("source_file_uploaded source=%s bucket=%s key=%s bytes=%d", source.id, source.minio_bucket, key, len(data))
    return {
        "status": "uploaded",
        "source_id": str(source_id),
        "bucket": source.minio_bucket,
        "key": key,
        "size": len(data),
    }


@router.delete("/{source_id}/files", status_code=200)
async def delete_source_file(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    key: str = Query(..., min_length=1),
):
    """Delete a file from the source's MinIO bucket.

    In live monitoring mode the removal event triggers pipeline sync, which
    drops the vectors for the removed file.
    """
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    from src.shared.storage import delete_object

    await delete_object(source.minio_bucket, key)
    logger.info("source_file_deleted source=%s bucket=%s key=%s", source.id, source.minio_bucket, key)
    return {
        "status": "deleted",
        "source_id": str(source_id),
        "bucket": source.minio_bucket,
        "key": key,
    }




# ── Sync triggers ─────────────────────────────────────────────────────────


@router.post("/{source_id}/sync", status_code=200)
async def trigger_source_sync(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Manually trigger a sync for all connectors of a source."""
    from src.ingestion_service.clients.source_sync import trigger_source_sync as do_sync
    return await do_sync(db, source_id)


# ── MinIO event webhook ──────────────────────────────────────────────────


@router.post("/{source_id}/events", status_code=200)
async def receive_source_events(
    source_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Webhook endpoint to receive MinIO bucket notification events.

    Called by MinIO when objects are created/removed in the source's bucket.
    For live monitoring mode, this triggers an immediate pipeline sync for affected files.
    """
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if not source.enabled:
        return {"status": "ignored", "reason": "source disabled"}

    # Check if any pipeline link has live mode
    live_pipeline_ids = []
    for ps in (source.pipelines or []):
        effective_mode = ps.monitor_mode or source.pipeline_monitor_mode
        if effective_mode == SourceMonitorMode.LIVE:
            live_pipeline_ids.append(str(ps.pipeline_id))

    if not live_pipeline_ids:
        return {"status": "ignored", "reason": "no live pipeline links"}

    # Parse MinIO event notification
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "reason": "invalid json"}

    records = payload.get("Records", [])
    if not records:
        return {"status": "ok", "records": 0}

    affected_keys: set[str] = set()
    for record in records:
        s3 = record.get("s3", {})
        obj = s3.get("object", {})
        key = obj.get("key")
        if key:
            affected_keys.add(key)

    logger.info(
        "source_events_received source=%s bucket=%s events=%d keys=%d pipelines=%d",
        source.id, source.minio_bucket, len(records), len(affected_keys), len(live_pipeline_ids),
    )

    from src.shared.queue.client import enqueue_sync_run
    for pipeline_id in live_pipeline_ids:
        await enqueue_sync_run(uuid.UUID(pipeline_id))

    return {
        "status": "ok",
        "records": len(records),
        "affected_keys": list(affected_keys),
        "pipelines_triggered": live_pipeline_ids,
    }
