import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.shared.config.settings import get_settings
from src.shared.db.models import Source, SourceConnector, SourceMonitorMode
from src.ingestion_service.core.gdrive_sync import sync_google_drive_to_minio
from src.ingestion_service.core.airbyte_connector import (
    sync_airbyte_connector_to_minio,
    validate_airbyte_connector_config,
    AIRBYTE_CONNECTOR_MAP
)
import httpx
from src.shared.queue.client import enqueue_sync_run
from src.shared.storage.s3_client import get_minio_client, watch_minio_bucket
logger = logging.getLogger(__name__)

_SYNCING_SOURCES: set[uuid.UUID] = set()

async def sync_source_from_pathway(db: AsyncSession, source_id: uuid.UUID) -> None:
    """Sync a source through Pathway Airbyte connector."""
    if source_id in _SYNCING_SOURCES:
        logger.info("pathway_sync_already_in_progress source=%s", source_id)
        return

    _SYNCING_SOURCES.add(source_id)
    try:
        await _do_sync_source_from_pathway(db, source_id)
    finally:
        _SYNCING_SOURCES.discard(source_id)

async def _do_sync_source_from_pathway(db: AsyncSession, source_id: uuid.UUID) -> None:
    source = await db.get(
        Source,
        source_id,
        options=(
            selectinload(Source.pipelines),
            selectinload(Source.connectors),
        ),
    )
    if not source:
        logger.error("pathway_sync_source_not_found source=%s", source_id)
        return
    if not source.enabled:
        logger.info("pathway_sync_skipped_disabled source=%s", source.id)
        return

    # Resolve connectors: prefer per-connector rows, fall back to legacy fields
    connectors: list[SourceConnector] = [
        c for c in (source.connectors or []) if c.enabled
    ]
    if not connectors and source.connector_type:
        # Legacy single-connector source — synthesize a connector row
        connectors = [
            SourceConnector(
                source_id=source.id,
                connector_type=source.connector_type,
                config=source.config or {},
                monitor_mode=SourceMonitorMode(source.connector_monitor_mode),
                sync_interval_minutes=source.connector_sync_interval_minutes,
                enabled=True,
            )
        ]

    if not connectors:
        logger.info("pathway_sync_no_connectors source=%s", source.id)
        return

    source.status = "syncing"
    source.error_message = None
    await db.commit()

    # Process each connector
    files_synced_total = 0
    bytes_transferred_total = 0
    
    for connector in connectors:
        try:
            logger.info(
                "Processing connector source=%s connector=%s type=%s",
                source.id,
                connector.id,
                connector.connector_type
            )
            
            # Validate connector configuration
            is_valid, error_msg = validate_airbyte_connector_config(
                connector.connector_type,
                connector.config or {}
            )
            if not is_valid:
                logger.error(
                    "Invalid connector config source=%s connector=%s error=%s",
                    source.id,
                    connector.id,
                    error_msg
                )
                connector.error_message = error_msg
                await db.commit()
                continue

            
            # Get MinIO bucket for this source
            minio_bucket = source.minio_bucket
            
            # Determine sync method based on connector type
            if connector.connector_type in ["local_folder", "local_dir"]:
                config = connector.config or {}
                res = await sync_local_dir_to_minio(
                    source_id=source.id,
                    connector_id=connector.id,
                    config=config,
                    bucket=minio_bucket,
                )
                files_synced_total += res.get("files_synced", 0)

            elif connector.connector_type in ["google_drive", "s3", "amazon_s3", "azure_blob", "azure"]:
                from src.ingestion_service.core.nifi_sync import sync_connector_via_nifi
                config = connector.config or {}
                res = await sync_connector_via_nifi(
                    source_id=source.id,
                    connector_id=connector.id,
                    connector_type=connector.connector_type,
                    config=config,
                    minio_bucket=minio_bucket,
                )
                files_synced_total += res.get("files_synced", 0)
            # Update connector sync status
            connector.status = "synced"
            connector.last_sync_at = datetime.now(UTC)
            connector.error_message = None
            await db.commit()
            
        except Exception as exc:
            logger.error(
                "Connector sync failed source=%s connector=%s error=%s",
                source.id,
                connector.id,
                str(exc),
                exc_info=True
            )
            connector.status = "error"
            connector.error_message = str(exc)
            await db.commit()
    # Update source status
    source.status = "idle"
    source.last_sync_at = datetime.now(UTC)
    logger.info(
        "Source sync completed source=%s files=%d bytes=%d",
        source.id,
        files_synced_total,
        bytes_transferred_total
    )
    await db.commit()
    # Trigger pipeline re-indexing for all linked pipelines
    await _trigger_pipeline_syncs(db, source)

    # Start monitoring MinIO for file changes in background
    start_minio_monitor(source_id)
    # Register live poller if source or any connector is configured in LIVE mode
    is_live = (source.connector_monitor_mode == SourceMonitorMode.LIVE) or any(
        c.monitor_mode == SourceMonitorMode.LIVE for c in connectors
    )
    if is_live:
        start_live_sync_poller(source.id, poll_interval_seconds=3)
async def _run_airbyte_connector(config: dict) -> dict:
    """Execute Airbyte connector with given configuration."""
    # Simplified placeholder - actual Airbyte execution would happen here
    # This would integrate with Pathway's connector runner
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{get_settings().airbyte_url}/v1/stream",
            json={
                "source": {
                    "type": "connector",
                    "connectorType": config["connector_type"]
                },
                "stream": [
                    {
                        "type": "full_refresh"
                    }
                ]
            }
        )
        return resp.json() if resp.status_code == 200 else {}

async def _trigger_pipeline_syncs(db: AsyncSession, source: "Source") -> None:
    """Enqueue pipeline re-indexing for all pipelines linked to source."""
    await source.awaitable_attrs.pipelines
    pipeline_ids = [pipeline.id for pipeline in source.pipelines or []]
    for pipeline_id in pipeline_ids:
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO pipeline_sync_queue (pipeline_id, source_id, created_at)
                    VALUES (:pipeline_id, :source_id, :created_at)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "pipeline_id": pipeline_id,
                    "source_id": source.id,
                    "created_at": datetime.utcnow(),
                },
            )
            await db.commit()
            await enqueue_sync_run(pipeline_id)
        except Exception as exc:
            logger.error("pipeline_sync_enqueue_failed pipeline=%s source=%s error=%s", pipeline_id, source.id, str(exc))
_MINIO_MONITOR_TASKS: dict[uuid.UUID, asyncio.Task] = {}

def start_minio_monitor(source_id: uuid.UUID) -> None:
    """Start background watch task on source MinIO bucket without holding DB sessions."""
    if source_id in _MINIO_MONITOR_TASKS and not _MINIO_MONITOR_TASKS[source_id].done():
        return

    async def _monitor_loop():
        from src.shared.db.session import AsyncSessionLocal
        bucket_name = None
        async with AsyncSessionLocal() as db:
            source = await db.get(Source, source_id)
            if source and source.minio_bucket:
                bucket_name = source.minio_bucket

        if not bucket_name:
            return

        try:
            async for event in watch_minio_bucket(bucket_name):
                if event.action in ["upload", "create", "store"]:
                    bucket_key = event.bucket_key
                    if bucket_key:
                        logger.info("MinIO file detected: %s", bucket_key)
                        async with AsyncSessionLocal() as db:
                            source = await db.get(Source, source_id)
                            if source:
                                await _trigger_pipeline_syncs(db, source)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("minio_monitor_error source=%s error=%s", source_id, exc)

    task = asyncio.create_task(_monitor_loop())
    _MINIO_MONITOR_TASKS[source_id] = task
async def sync_local_dir_to_minio(
    connector_id: uuid.UUID | str,
    config: dict[str, Any],
    bucket: str,
) -> dict[str, Any]:
    """Sync a local filesystem directory to a MinIO bucket with full CRUD reflection (Add, Replace, Delete)."""
    import os
    from pathlib import Path
    from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object, ensure_bucket

    folder_path = config.get("folder_path") or config.get("path") or config.get("dir")
    if not folder_path or not os.path.exists(folder_path):
        logger.warning("local_dir_not_found path=%s source=%s", folder_path, source_id)
        return {"files_synced": 0, "files_added": 0, "files_updated": 0, "files_deleted": 0}

    await ensure_bucket(bucket)
    base_dir = Path(folder_path)

    # Scan active local files
    local_files: dict[str, Path] = {}
    for p in base_dir.rglob("*"):
        if p.is_file():
            rel_path = str(p.relative_to(base_dir)).replace("\\", "/")
            local_files[rel_path] = p

    # Query MinIO existing objects for this connector
    prefix = f"connectors/{connector_id}/"
    existing_objects = await list_objects(bucket, prefix=prefix)
    minio_files: dict[str, Any] = {}
    for obj in existing_objects:
        rel_key = obj.key[len(prefix):]
        minio_files[rel_key] = obj

    added = 0
    updated = 0
    deleted = 0
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    # Add & Replace / Update
    for rel_path, file_path in local_files.items():
        try:
            stat = file_path.stat()
            mtime_str = str(stat.st_mtime)
            size = stat.st_size
            target_key = f"{prefix}{rel_path}"

            needs_upload = False
            is_update = False

            if rel_path not in minio_files:
                needs_upload = True
            else:
                existing_obj = minio_files[rel_path]
                head = await head_object(bucket, target_key)
                meta = head.get("Metadata", {}) if head else {}
                old_mtime = meta.get("remote-modified-at", "")

                if old_mtime != mtime_str or existing_obj.size != size:
                    needs_upload = True
                    is_update = True

            if needs_upload:
                with open(file_path, "rb") as f:
                    data = f.read()
                await put_object(
                    bucket_name=bucket,
                    key=target_key,
                    data=data,
                    metadata={
                        "source-id": str(source_id),
                        "connector-id": str(connector_id),
                        "remote-modified-at": mtime_str,
                        "sync-timestamp": timestamp,
                    },
                )
                if is_update:
                    updated += 1
                    logger.info("local_file_updated source=%s key=%s", source_id, target_key)
                else:
                    added += 1
                    logger.info("local_file_added source=%s key=%s", source_id, target_key)
        except Exception as exc:
            logger.warning("local_file_sync_failed path=%s error=%s", rel_path, exc)

    # Delete (Files removed locally are deleted from MinIO)
    for rel_path, minio_obj in minio_files.items():
        if rel_path not in local_files:
            try:
                await delete_object(bucket, minio_obj.key)
                deleted += 1
                logger.info("local_file_deleted source=%s key=%s", source_id, minio_obj.key)
            except Exception as exc:
                logger.error("local_file_delete_failed source=%s key=%s error=%s", source_id, minio_obj.key, exc)

    return {
        "files_synced": len(local_files),
        "files_added": added,
        "files_updated": updated,
        "files_deleted": deleted,
    }


_LIVE_POLLE_TASKS: dict[uuid.UUID, asyncio.Task] = {}

def start_live_sync_poller(source_id: uuid.UUID, poll_interval_seconds: int = 3) -> None:
    """Start continuous background polling for live-mode sources (default 3s interval for <5s latency)."""
    import asyncio
    from src.shared.db.session import AsyncSessionLocal

    if source_id in _LIVE_POLLE_TASKS and not _LIVE_POLLE_TASKS[source_id].done():
        return

    async def _poller_loop():
        logger.info("live_sync_poller_started source=%s interval=%ds", source_id, poll_interval_seconds)
        while True:
            try:
                await asyncio.sleep(poll_interval_seconds)
                async with AsyncSessionLocal() as db:
                    await sync_source_from_pathway(db, source_id)
            except asyncio.CancelledError:
                logger.info("live_sync_poller_cancelled source=%s", source_id)
                break
            except Exception as exc:
                logger.error("live_sync_poller_error source=%s error=%s", source_id, exc)

    task = asyncio.create_task(_poller_loop())
    _LIVE_POLLE_TASKS[source_id] = task


async def init_all_live_sync_pollers() -> None:
    """Initialize live sync background pollers for all sources configured in LIVE mode."""
    from sqlalchemy import select
    from src.shared.db.session import AsyncSessionLocal
    from src.shared.db.models import Source, SourceConnector, SourceMonitorMode

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Source).where(Source.enabled.is_(True)))
            sources = result.scalars().all()
            for source in sources:
                conn_res = await db.execute(
                    select(SourceConnector).where(SourceConnector.source_id == source.id)
                )
                connectors = conn_res.scalars().all()
                is_live = (source.connector_monitor_mode == SourceMonitorMode.LIVE) or any(
                    c.monitor_mode == SourceMonitorMode.LIVE for c in connectors
                )
                if is_live:
                    start_live_sync_poller(source.id, poll_interval_seconds=3)
    except Exception as exc:
        logger.error("init_all_live_sync_pollers_error: %s", exc)