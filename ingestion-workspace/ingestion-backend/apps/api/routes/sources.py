"""Sources API — CRUD for external data sources backed by Airbyte/Pathway connectors.

Each source is a MinIO bucket that can have multiple Airbyte connectors feeding into it.
Two monitoring modes at two points:
  - Connectors → Source: how connectors sync into the bucket (per-connector)
  - Source → Pipeline: how bucket changes trigger pipeline re-indexing (per-link or source default)
"""

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.file_manager.utils.paths import sanitize_directory_name, sanitize_file_name, storage_root
from src.shared.db.session import get_db
from src.shared.storage import ensure_bucket
from src.shared.db.models import Source, SourceConnector, SourceMonitorMode, Pipeline, PipelineSource, KnowledgeProfileSource
from src.shared.config.settings import get_settings
router = APIRouter(prefix="/api/sources", tags=["sources"])
settings = get_settings()

CONNECTOR_OPTIONS = [
    {"id": "local_filesystem", "label": "Local File System", "description": "Local workspace folder storage"},
    {"id": "google_drive", "label": "Google Drive", "description": "Sync files from Google Drive"},
    {"id": "google_sheets", "label": "Google Sheets", "description": "Sync spreadsheets from Google Sheets"},
    {"id": "gcs", "label": "Google Cloud Storage", "description": "Sync files from GCS buckets"},
    {"id": "s3", "label": "Amazon S3", "description": "Sync files from S3 buckets"},
    {"id": "azure_blob", "label": "Azure Blob Storage", "description": "Sync files from Azure Blob"},
    {"id": "onedrive", "label": "Microsoft OneDrive", "description": "Sync files from OneDrive"},
    {"id": "sharepoint", "label": "Microsoft SharePoint", "description": "Sync files from SharePoint"},
    {"id": "postgres", "label": "PostgreSQL", "description": "CDC sync from PostgreSQL database"},
    {"id": "web_scrape", "label": "Web Scraper", "description": "Crawl & extract content from websites"},
]


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    source_type: Literal["minio", "local_filesystem"] = "minio"
    connector_type: str = "local_filesystem"
    config: dict = Field(default_factory=dict)
    connector_monitor_mode: str = "live"
    connector_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    pipeline_monitor_mode: str = "live"
    pipeline_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    # Legacy fallback field
    monitor_mode: str | None = None
    sync_interval_minutes: int | None = None


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    connector_monitor_mode: str | None = None
    connector_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    pipeline_monitor_mode: str | None = None
    pipeline_sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    config: dict | None = None
    # Legacy fallbacks
    monitor_mode: str | None = None
    sync_interval_minutes: int | None = None


class ConnectorCreateRequest(BaseModel):
    connector_type: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


class ConnectorUpdateRequest(BaseModel):
    config: dict | None = None
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


class SourcePipelineLinkRequest(BaseModel):
    monitor_mode: str | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


def _connector_to_dict(c: SourceConnector) -> dict:
    return {
        "id": str(c.id),
        "source_id": str(c.source_id),
        "connector_type": c.connector_type,
        "config": c.config or {},
        "enabled": c.enabled,
        "status": c.status,
        "sync_interval_minutes": c.sync_interval_minutes,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "error_message": c.error_message,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _is_local_source(s: Source) -> bool:
    if s.connector_type == "local_filesystem":
        return True
    if (s.config or {}).get("source_type") == "local_filesystem":
        return True
    if s.minio_bucket and s.minio_bucket.startswith("local-"):
        return True
    return False

def _trigger_sync_in_background(source: Source) -> None:
    async def _runner():
        from src.shared.db.session import AsyncSessionLocal
        from src.ingestion_service.core.pathway_sync import _trigger_pipeline_syncs
        try:
            async with AsyncSessionLocal() as db_session:
                s = await db_session.get(Source, source.id)
                if s:
                    await _trigger_pipeline_syncs(db_session, s)
        except Exception as exc:
            logger.warning("background_fanout_sync_failed source=%s error=%s", source.id, exc)
    asyncio.create_task(_runner())


async def _source_to_dict(s: Source) -> dict:
    try:
        pipelines = s.pipelines or []
    except Exception:
        pipelines = []
    try:
        connectors = s.connectors or []
    except Exception:
        connectors = []
    is_local = _is_local_source(s)
    return {
        "id": str(s.id),
        "name": s.name,
        "source_type": "local_filesystem" if is_local else "minio",
        "local_path": (s.config or {}).get("local_path") if is_local else None,
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
        "total_files": getattr(s, "total_files", 0) or 0,
        "total_size_bytes": getattr(s, "total_size_bytes", 0) or 0,
        "error_message": s.error_message,
        "pipeline_ids": [str(ps.pipeline_id) for ps in pipelines],
        "pipeline_links": [
            {
                "pipeline_id": str(ps.pipeline_id),
                "monitor_mode": ps.monitor_mode.value if ps.monitor_mode else None,
                "sync_interval_minutes": ps.sync_interval_minutes,
            }
            for ps in pipelines
        ],
        "connectors": [_connector_to_dict(c) for c in connectors],
        "connector_count": len(connectors),
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
    sources = result.scalars().all()
    return {"sources": [await _source_to_dict(s) for s in sources]}


@router.post("", status_code=201)
async def create_source(
    body: SourceCreateRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create a new external data source or local filesystem source."""
    is_local = body.source_type == "local_filesystem" or body.connector_type == "local_filesystem"

    # Check name uniqueness
    existing = await db.execute(select(Source).where(Source.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise ConflictError("SOURCE_EXISTS", f"A source named '{body.name}' already exists.")

    source_id = uuid.uuid4()

    if is_local:
        import re
        safe_name = re.sub(r"[^a-z0-9_-]", "_", body.name.strip().lower())
        if not safe_name:
            safe_name = "local_source"
        folder_name = f"{safe_name}-{str(source_id)[:8]}"
        local_dir = storage_root() / "local_sources" / folder_name
        local_dir.mkdir(parents=True, exist_ok=True)

        bucket = f"local-{folder_name}"
        config = body.config or {}
        config["source_type"] = "local_filesystem"
        config["folder_name"] = folder_name
        config["local_path"] = str(local_dir)

        source = Source(
            id=source_id,
            name=body.name.strip(),
            connector_type="local_filesystem",
            config=config,
            connector_monitor_mode=SourceMonitorMode(body.connector_monitor_mode),
            connector_sync_interval_minutes=body.connector_sync_interval_minutes,
            pipeline_monitor_mode=SourceMonitorMode(body.pipeline_monitor_mode),
            pipeline_sync_interval_minutes=body.pipeline_sync_interval_minutes,
            minio_bucket=bucket,
            status="synced",
            total_files=0,
            total_size_bytes=0,
        )
    else:
        # MinIO bucket source
        bucket = _make_bucket_name(str(source_id), body.name)
        try:
            await ensure_bucket(bucket)
        except Exception as exc:
            logger.error("Failed creating MinIO bucket %s: %s", bucket, exc)
            raise ValidationError("STORAGE_ERROR", f"Failed to provision bucket '{bucket}': {exc}")

        # Handle legacy monitor_mode / sync_interval_minutes fallbacks
        conn_mode = body.connector_monitor_mode or body.monitor_mode or "live"
        conn_interval = body.connector_sync_interval_minutes or body.sync_interval_minutes
        pipe_mode = body.pipeline_monitor_mode or "live"

        source = Source(
            id=source_id,
            name=body.name.strip(),
            connector_type=body.connector_type,
            config=body.config,
            connector_monitor_mode=SourceMonitorMode(conn_mode),
            connector_sync_interval_minutes=conn_interval,
            pipeline_monitor_mode=SourceMonitorMode(pipe_mode),
            pipeline_sync_interval_minutes=body.pipeline_sync_interval_minutes,
            minio_bucket=bucket,
            status="disconnected",
            total_files=0,
            total_size_bytes=0,
        )

        # Create auto-configured primary connector if connector_type is a specific provider
        if body.connector_type and body.connector_type not in ("none", "local_filesystem", "minio"):
            connector = SourceConnector(
                id=uuid.uuid4(),
                source_id=source_id,
                connector_type=body.connector_type,
                config=body.config or {},
                enabled=True,
                status="disconnected",
                sync_interval_minutes=conn_interval,
            )
            db.add(connector)

    db.add(source)
    await db.commit()

    # Re-fetch with relationships loaded
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.pipelines), selectinload(Source.connectors))
        .where(Source.id == source_id)
    )
    created = result.scalar_one()
    return await _source_to_dict(created)


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

    await db.commit()

    # If pipeline monitor mode changed to/from continuous, notify background monitors
    if old_pipeline_mode != source.pipeline_monitor_mode:
        _trigger_sync_in_background(source)

    result = await db.execute(
        select(Source)
        .options(selectinload(Source.pipelines), selectinload(Source.connectors))
        .where(Source.id == source_id)
    )
    updated = result.scalar_one()
    return await _source_to_dict(updated)


@router.delete("/{source_id}", status_code=200)
async def delete_source(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    await db.execute(delete(KnowledgeProfileSource).where(KnowledgeProfileSource.source_id == source_id))
    await db.execute(delete(PipelineSource).where(PipelineSource.source_id == source_id))

    is_local = _is_local_source(source)
    if is_local:
        try:
            folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
            local_dir = storage_root() / "local_sources" / folder_name
            if local_dir.exists():
                await asyncio.to_thread(shutil.rmtree, local_dir, True)
                logger.info("Deleted local source directory %s for source %s", local_dir, source_id)
        except Exception as exc:
            logger.error("Failed deleting local source directory for source %s: %s", source_id, exc)
    elif source.minio_bucket:
        try:
            from src.shared.storage import delete_bucket as s3_delete_bucket
            await s3_delete_bucket(source.minio_bucket)
        except Exception as exc:
            logger.error("Failed deleting MinIO bucket %s for source %s: %s", source.minio_bucket, source_id, exc)
    await db.delete(source)
    await db.commit()
    return {"status": "deleted", "id": str(source_id)}


@router.get("/{source_id}/connectors")
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
    """Attach a new connector to a source."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    if _is_local_source(source):
        raise ValidationError(
            "CONNECTORS_NOT_SUPPORTED",
            "Local File System sources do not support connectors."
        )

    connector = SourceConnector(
        id=uuid.uuid4(),
        source_id=source_id,
        connector_type=body.connector_type,
        config=body.config,
        enabled=body.enabled,
        status="disconnected",
        sync_interval_minutes=body.sync_interval_minutes,
    )
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    return _connector_to_dict(connector)


@router.patch("/{source_id}/connectors/{connector_id}", status_code=200)
async def update_source_connector(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    body: ConnectorUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a connector's config, enabled state, or sync interval."""
    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.id == connector_id,
            SourceConnector.source_id == source_id,
        )
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found for this source.")

    if body.config is not None:
        connector.config = body.config
    if body.enabled is not None:
        connector.enabled = body.enabled
    if body.sync_interval_minutes is not None:
        connector.sync_interval_minutes = body.sync_interval_minutes

    await db.commit()
    await db.refresh(connector)
    return _connector_to_dict(connector)


@router.delete("/{source_id}/connectors/{connector_id}", status_code=200)
async def delete_source_connector(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a connector from a source."""
    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.id == connector_id,
            SourceConnector.source_id == source_id,
        )
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found for this source.")

    await db.delete(connector)
    await db.commit()
    return {"status": "deleted", "id": str(connector_id)}


@router.post("/{source_id}/connectors/{connector_id}/sync", status_code=200)
async def trigger_connector_sync(
    source_id: uuid.UUID,
    connector_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually trigger a sync for a specific connector."""
    result = await db.execute(
        select(SourceConnector).where(
            SourceConnector.id == connector_id,
            SourceConnector.source_id == source_id,
        )
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise NotFoundError("CONNECTOR_NOT_FOUND", "Connector not found.")

    if not connector.enabled:
        raise ValidationError("CONNECTOR_DISABLED", "Cannot sync a disabled connector.")

    connector.status = "syncing"
    connector.last_sync_at = datetime.now(timezone.utc)
    await db.commit()

    # Trigger background sync job
    source = await db.get(Source, source_id)
    if source:
        _trigger_sync_in_background(source)

    return _connector_to_dict(connector)


@router.post("/{source_id}/pipeline/{pipeline_id}", status_code=200)
async def link_source_to_pipeline(
    source_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    body: SourcePipelineLinkRequest | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Link a source to a pipeline with optional custom monitor mode overrides."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    existing = await db.execute(
        select(PipelineSource).where(
            PipelineSource.pipeline_id == pipeline_id,
            PipelineSource.source_id == source_id,
        )
    )
    link = existing.scalar_one_or_none()

    monitor_mode = SourceMonitorMode(body.monitor_mode) if body and body.monitor_mode else None
    sync_interval = body.sync_interval_minutes if body else None

    if link:
        link.monitor_mode = monitor_mode
        link.sync_interval_minutes = sync_interval
    else:
        link = PipelineSource(
            pipeline_id=pipeline_id,
            source_id=source_id,
            monitor_mode=monitor_mode,
            sync_interval_minutes=sync_interval,
        )
        db.add(link)

    await db.commit()
    _trigger_sync_in_background(source)
    return {
        "status": "linked",
        "source_id": str(source_id),
        "pipeline_id": str(pipeline_id),
        "monitor_mode": monitor_mode.value if monitor_mode else None,
        "sync_interval_minutes": sync_interval,
    }


@router.delete("/{source_id}/pipeline/{pipeline_id}", status_code=200)
async def unlink_source_from_pipeline(
    source_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unlink a source from a pipeline."""
    result = await db.execute(
        select(PipelineSource).where(
            PipelineSource.pipeline_id == pipeline_id,
            PipelineSource.source_id == source_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise NotFoundError("LINK_NOT_FOUND", "Link between source and pipeline not found.")

    await db.delete(link)
    await db.commit()
    return {"status": "unlinked", "source_id": str(source_id), "pipeline_id": str(pipeline_id)}


@router.get("/{source_id}/files", status_code=200)
async def list_source_files(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    prefix: str = Query(default=""),
):
    """List files in the source (MinIO bucket or Local File System)."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    is_local = _is_local_source(source)
    if is_local:
        folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
        local_dir = storage_root() / "local_sources" / folder_name
        local_dir.mkdir(parents=True, exist_ok=True)
        file_entries = []
        for p in local_dir.rglob("*"):
            if p.is_file():
                rel_key = str(p.relative_to(local_dir)).replace("\\", "/")
                if prefix and not rel_key.startswith(prefix):
                    continue
                stat = p.stat()
                file_entries.append({
                    "key": rel_key,
                    "size": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
        return {
            "source_id": str(source_id),
            "bucket": source.minio_bucket,
            "files": file_entries,
        }

    from src.shared.storage import list_objects as s3_list

    try:
        files = await s3_list(source.minio_bucket, prefix=prefix)
    except Exception as exc:
        logger.warning("Failed listing MinIO files for bucket %s: %s", source.minio_bucket, exc)
        files = []

    return {
        "source_id": str(source_id),
        "bucket": source.minio_bucket,
        "files": [
            {
                "key": f.key,
                "size": f.size,
                "last_modified": f.last_modified.isoformat() if f.last_modified else None,
            }
            for f in files
        ],
    }


async def _update_source_metrics(db: AsyncSession, source: Source) -> None:
    """Recalculate total_files and total_size_bytes for a source and update DB."""
    try:
        total_files = 0
        total_size = 0
        is_local = _is_local_source(source)
        if is_local:
            folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
            local_dir = storage_root() / "local_sources" / folder_name
            if local_dir.exists() and local_dir.is_dir():
                for p in local_dir.rglob("*"):
                    if p.is_file():
                        total_files += 1
                        total_size += p.stat().st_size
        elif source.minio_bucket:
            from src.shared.storage import list_objects as s3_list
            try:
                objects = await s3_list(source.minio_bucket)
                total_files = len(objects)
                total_size = sum(obj.size for obj in objects)
            except Exception as exc:
                logger.warning("Failed listing MinIO bucket %s for metrics: %s", source.minio_bucket, exc)

        source.total_files = total_files
        source.total_size_bytes = total_size
        await db.commit()
    except Exception as exc:
        logger.error("Failed updating metrics for source %s: %s", source.id, exc)


@router.post("/{source_id}/files", status_code=201)
async def upload_source_file(
    source_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Upload file(s) into the source (MinIO bucket or Local File System folder)."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    form = await request.form()
    raw_uploads = form.getlist("file") + form.getlist("files")
    if not raw_uploads:
        single = form.get("file") or form.get("files")
        if single:
            raw_uploads = [single]

    if not raw_uploads:
        raise ValidationError("FILE_REQUIRED", "Multipart field 'file' or 'files' is required.")

    is_local = _is_local_source(source)
    if is_local:
        folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
        local_dir = storage_root() / "local_sources" / folder_name
        local_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        for item in raw_uploads:
            if not hasattr(item, "filename") or not item.filename:
                continue
            data = await item.read()
            clean_name = sanitize_file_name(item.filename)
            file_path = local_dir / clean_name
            file_path.write_bytes(data)
            saved_files.append({"key": clean_name, "size": len(data)})

        logger.info("local_source_file_uploaded source=%s folder=%s count=%d", source.id, folder_name, len(saved_files))
        await _update_source_metrics(db, source)
        _trigger_sync_in_background(source)
        return {
            "status": "uploaded",
            "source_id": str(source_id),
            "bucket": source.minio_bucket,
            "key": saved_files[0]["key"] if saved_files else "",
            "size": saved_files[0]["size"] if saved_files else 0,
            "files": saved_files,
        }

    # MinIO upload path
    upload = raw_uploads[0]
    data = await upload.read()
    if not data:
        raise ValidationError("EMPTY_FILE", "Uploaded file is empty.")

    key = sanitize_file_name(getattr(upload, "filename", "file"))
    from src.shared.storage import ensure_bucket, put_object

    await ensure_bucket(source.minio_bucket)
    await put_object(source.minio_bucket, key, data)
    logger.info("source_file_uploaded source=%s bucket=%s key=%s bytes=%d", source.id, source.minio_bucket, key, len(data))
    await _update_source_metrics(db, source)
    _trigger_sync_in_background(source)
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
    """Delete a file from the source (MinIO bucket or Local File System)."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    is_local = _is_local_source(source)
    if is_local:
        folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
        local_dir = storage_root() / "local_sources" / folder_name
        file_path = local_dir / key
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
        logger.info("local_source_file_deleted source=%s folder=%s key=%s", source.id, folder_name, key)
        await _update_source_metrics(db, source)
        _trigger_sync_in_background(source)
        return {
            "status": "deleted",
            "source_id": str(source_id),
            "bucket": source.minio_bucket,
            "key": key,
        }

    from src.shared.storage import delete_object
    await delete_object(source.minio_bucket, key)
    logger.info("source_file_deleted source=%s bucket=%s key=%s", source.id, source.minio_bucket, key)
    await _update_source_metrics(db, source)
    _trigger_sync_in_background(source)
    return {
        "status": "deleted",
        "source_id": str(source_id),
        "bucket": source.minio_bucket,
        "key": key,
    }


@router.get("/{source_id}/files/content", status_code=200)
async def get_source_file_content(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    key: str = Query(..., min_length=1),
):
    """Fetch the content of a file stored in the source (MinIO bucket or Local File System)."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    is_local = _is_local_source(source)
    if is_local:
        folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
        local_dir = storage_root() / "local_sources" / folder_name
        file_path = local_dir / key
        if not file_path.exists() or not file_path.is_file():
            raise NotFoundError("FILE_NOT_FOUND", f"Could not retrieve file '{key}'")
        data = file_path.read_bytes()
        media_type = "application/octet-stream"
        ext = file_path.suffix.lower()
        if ext in (".txt", ".log"):
            media_type = "text/plain; charset=utf-8"
        elif ext == ".json":
            media_type = "application/json"
        elif ext == ".pdf":
            media_type = "application/pdf"
        elif ext in (".png", ".jpg", ".jpeg"):
            media_type = f"image/{ext.lstrip('.')}"
        return Response(content=data, media_type=media_type)

    from src.shared.storage import get_object

    try:
        data = await get_object(source.minio_bucket, key)
    except Exception as exc:
        raise NotFoundError("FILE_NOT_FOUND", f"Could not retrieve file '{key}' from MinIO: {exc}")

    media_type = "application/octet-stream"
    ext = key.split(".")[-1].lower() if "." in key else ""
    if ext in ("txt", "log"):
        media_type = "text/plain; charset=utf-8"
    elif ext == "json":
        media_type = "application/json"
    elif ext == "pdf":
        media_type = "application/pdf"
    elif ext in ("png", "jpg", "jpeg"):
        media_type = f"image/{ext}"

    return Response(content=data, media_type=media_type)


@router.post("/{source_id}/sync", status_code=200)
async def trigger_source_sync(
    source_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Manually trigger sync for all connectors and linked pipelines of a source."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    _trigger_sync_in_background(source)
    source.last_sync_at = datetime.now(timezone.utc)
    source.status = "synced"
    await db.commit()
    return {"status": "sync_triggered", "source_id": str(source_id)}


@router.post("/{source_id}/events", status_code=200)
async def receive_source_events(
    source_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Webhook endpoint for MinIO bucket notification events."""
    source = await db.get(Source, source_id)
    if not source:
        raise NotFoundError("SOURCE_NOT_FOUND", "Source not found.")

    body = await request.json()
    logger.info("MinIO bucket event received for source %s: %s", source_id, body)
    _trigger_sync_in_background(source)
    return {"status": "event_processed", "source_id": str(source_id)}
