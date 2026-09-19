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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx
from src.ingestion_service.core.airbyte_connector import validate_airbyte_connector_config
from src.shared.queue.client import enqueue_sync_run
from src.shared.storage.s3_client import get_minio_client, watch_minio_bucket
logger = logging.getLogger(__name__)

_SYNCING_SOURCES: set[uuid.UUID] = set()
_MINIO_MONITOR_TASKS: dict[uuid.UUID, asyncio.Task] = {}
_LOCAL_FS_MONITOR_TASKS: dict[uuid.UUID, asyncio.Task] = {}
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
    print(f"==== ENTERED do_sync with source_id={source_id} ====")
    source = await db.get(
        Source,
        source_id,
        options=[selectinload(Source.connectors), selectinload(Source.pipelines)]
    )
    if not source:
        print(f"==== SOURCE {source_id} NOT FOUND ====")
        logger.error("Source %s not found during pathway sync", source_id)
        return
    
    print(f"==== SOURCE FOUND {source.id} status={source.status} enabled={source.enabled} ====")
    
    if not source.enabled:
        logger.warning(
            "Source %s is disabled, skipping sync",
            source.id
        )
        return
    if not source:
        logger.error("pathway_sync_source_not_found source=%s", source_id)
        return
    if not source.enabled:
        logger.info("pathway_sync_skipped_disabled source=%s", source.id)
        return

    # Resolve connectors: prefer per-connector rows, fall back to legacy fields.
    # "minio" and "local_filesystem" are source markers, not connector ids, so
    # they must not synthesize a connector that no NiFi sync path can serve.
    connectors: list[SourceConnector] = [
        c for c in (source.connectors or []) if c.enabled
    ]
    marker_types = {"minio", "minio_manual", "manual_upload", "local_filesystem"}
    if not connectors and source.connector_type and source.connector_type not in marker_types:
        # Legacy single-connector source — synthesize a connector row
        connectors = [
            SourceConnector(
                source_id=source.id,
                connector_type=source.connector_type,
                config=source.config or {},
                monitor_mode=SourceMonitorMode(source.connector_monitor_mode),
                sync_interval_minutes=source.connector_sync_interval_minutes,
                sync_interval_seconds=getattr(source, "connector_sync_interval_seconds", None),
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
            
            # Determine sync method based on connector type (all connectors route through NiFi Connector Engine)
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
    # Update source status and file counts from MinIO bucket
    try:
        from src.shared.storage.s3_client import list_objects
        all_objs = await list_objects(source.minio_bucket)
        source.total_files = len(all_objs)
        source.total_size_bytes = sum(o.size for o in all_objs)
    except Exception as exc:
        logger.warning("Failed computing total_files for source %s: %s", source.id, exc)
    source.status = "idle"
    source.last_sync_at = datetime.now(UTC)
    logger.info(
        "Source sync completed source=%s files=%d bytes=%d",
        source.id,
        files_synced_total,
        bytes_transferred_total
    )
    print("==== BEFORE COMMIT IDLE ====")
    await db.commit()
    print("==== AFTER COMMIT IDLE ====")
    # Trigger pipeline re-indexing for all linked pipelines
    try:
        print("==== TRIGGERING PIPELINE SYNC ====")
        await _trigger_pipeline_syncs(db, source)
    except Exception as exc:
        logger.exception("pipeline_syncs_trigger_failed source=%s error=%s", source.id, str(exc))

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
    """Trigger Knowledge Profile fanout sync and pipeline re-indexing for linked source."""
    try:
        from src.ingestion_service.core.universal_fanout import execute_universal_fanout_sync
        
        # Find matching knowledge profiles linked to this source
        from sqlalchemy import select
        from src.shared.db.models import KnowledgeProfileSource
        
        stmt = select(KnowledgeProfileSource.knowledge_profile_id).where(KnowledgeProfileSource.source_id == source.id)
        res = await db.execute(stmt)
        kp_ids = res.scalars().all()
        
        for kp_id in kp_ids:
            await execute_universal_fanout_sync(db, kp_id)
    except Exception as exc:
        logger.error(
            "knowledge_profile_fanout_sync_failed source=%s error=%s",
            source.id,
            str(exc)
        )

    try:
        print("==== CHECKING LINKED PIPELINES ====")
        if not source.pipelines:
            print("==== NO LINKED PIPELINES ====")
            return
            
        from src.shared.queue.client import enqueue_sync_run
        for p_link in source.pipelines:
            pipeline_id = p_link.pipeline_id
            logger.info("pipeline_sync_triggered pipeline=%s source=%s", pipeline_id, source.id)
            print(f"==== ENQUEUING PIPELINE SYNC {pipeline_id} ====")
            try:
                await enqueue_sync_run(pipeline_id)
            except Exception as exc:
                logger.error("pipeline_sync_enqueue_failed pipeline=%s source=%s error=%s", pipeline_id, source.id, str(exc))
    except Exception as exc:
        print(f"==== PIPELINE TRIGGER FAILED: {exc} ====")
        logger.error("pipeline_syncs_trigger_failed loop error=%s", str(exc))

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


def start_local_fs_monitor(source_id: uuid.UUID) -> None:
    """Start Pathway local directory CRUD monitor task watching storage/local_sources/<folder_name>."""
    if source_id in _LOCAL_FS_MONITOR_TASKS and not _LOCAL_FS_MONITOR_TASKS[source_id].done():
        return

    async def _monitor_loop():
        from src.shared.db.session import AsyncSessionLocal
        from src.shared.storage import storage_root

        folder_name = None
        async with AsyncSessionLocal() as db:
            source = await db.get(Source, source_id)
            if source:
                folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")

        if not folder_name:
            return

        local_dir = storage_root() / "local_sources" / folder_name
        local_dir.mkdir(parents=True, exist_ok=True)

        last_snapshot: dict[str, float] = {}

        while True:
            try:
                await asyncio.sleep(2.0)
                if not local_dir.exists():
                    continue

                current_snapshot: dict[str, float] = {}
                for p in local_dir.rglob("*"):
                    if p.is_file():
                        try:
                            stat = p.stat()
                            rel_path = str(p.relative_to(local_dir)).replace("\\", "/")
                            current_snapshot[rel_path] = stat.st_mtime
                        except Exception:
                            pass

                if last_snapshot and current_snapshot != last_snapshot:
                    logger.info("local_fs_change_detected source=%s folder=%s files=%d", source_id, folder_name, len(current_snapshot))
                    async with AsyncSessionLocal() as db:
                        source = await db.get(Source, source_id)
                        if source:
                            await _trigger_pipeline_syncs(db, source)

                last_snapshot = current_snapshot
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("local_fs_monitor_error source=%s error=%s", source_id, exc)
                await asyncio.sleep(5.0)

    task = asyncio.create_task(_monitor_loop())
    _LOCAL_FS_MONITOR_TASKS[source_id] = task
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


_SOURCE_POLLER_TASKS: dict[uuid.UUID, asyncio.Task] = {}

def stop_source_poller(source_id: uuid.UUID) -> None:
    """Stop and cancel any active background poller task for a source."""
    task = _SOURCE_POLLER_TASKS.pop(source_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Stopped background poller task for source %s", source_id)

def start_live_sync_poller(source_id: uuid.UUID, poll_interval_seconds: int = 3) -> None:
    """Legacy alias for register_source_poller."""
    asyncio.create_task(register_source_poller(source_id))

async def register_source_poller(source_id: uuid.UUID) -> None:
    """Register or update continuous live/scheduled background polling for a source."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from src.shared.db.session import AsyncSessionLocal
    from src.shared.db.models import Source, SourceConnector, SourceMonitorMode

    async with AsyncSessionLocal() as db:
        source = await db.get(
            Source,
            source_id,
            options=(selectinload(Source.connectors),),
        )
        if not source or not source.enabled:
            stop_source_poller(source_id)
            return

        connectors = source.connectors or []
        is_live = (source.connector_monitor_mode == SourceMonitorMode.LIVE) or any(
            c.monitor_mode == SourceMonitorMode.LIVE for c in connectors
        )

        stop_source_poller(source_id)

        if is_live:
            poll_interval_seconds = 3
            logger.info("Starting INSTANTANEOUS LIVE background poller for source %s (interval=%ds)", source_id, poll_interval_seconds)

            async def _live_loop():
                while True:
                    try:
                        await asyncio.sleep(poll_interval_seconds)
                        async with AsyncSessionLocal() as db_inner:
                            await sync_source_from_pathway(db_inner, source_id)
                    except asyncio.CancelledError:
                        logger.info("Live poller task cancelled for source %s", source_id)
                        break
                    except Exception as exc:
                        logger.error("Live poller loop error for source %s: %s", source_id, exc)

            task = asyncio.create_task(_live_loop())
            _SOURCE_POLLER_TASKS[source_id] = task

        else:
            # SCHEDULED mode — seconds take priority over minutes.
            interval_seconds = source.connector_sync_interval_seconds
            if not interval_seconds:
                for c in connectors:
                    if c.sync_interval_seconds:
                        interval_seconds = c.sync_interval_seconds
                        break
            if not interval_seconds:
                interval_minutes = source.connector_sync_interval_minutes
                if not interval_minutes:
                    for c in connectors:
                        if c.sync_interval_minutes:
                            interval_minutes = c.sync_interval_minutes
                            break
                if not interval_minutes:
                    interval_minutes = 5  # default 5 minutes
                interval_seconds = interval_minutes * 60

            interval_seconds = max(5, interval_seconds)
            logger.info("Starting PRECISE SCHEDULED background poller for source %s (interval=%ds)", source_id, interval_seconds)

            async def _scheduled_loop():
                while True:
                    try:
                        await asyncio.sleep(interval_seconds)
                        async with AsyncSessionLocal() as db_inner:
                            await sync_source_from_pathway(db_inner, source_id)
                    except asyncio.CancelledError:
                        logger.info("Scheduled poller task cancelled for source %s", source_id)
                        break
                    except Exception as exc:
                        logger.error("Scheduled poller loop error for source %s: %s", source_id, exc)

            task = asyncio.create_task(_scheduled_loop())
            _SOURCE_POLLER_TASKS[source_id] = task

        # Trigger immediate initial sync on registration
        asyncio.create_task(_trigger_initial_sync(source_id))

async def _trigger_initial_sync(source_id: uuid.UUID) -> None:
    """Run immediate initial sync on source registration so new/updated sources don't wait for sleep."""
    try:
        from src.shared.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await sync_source_from_pathway(db, source_id)
    except Exception as exc:
        logger.warning("Initial background sync error for source %s: %s", source_id, exc)

async def init_all_source_pollers() -> None:
    """Initialize background pollers (live & scheduled) for all enabled sources on server startup."""
    from sqlalchemy import select
    from src.shared.db.session import AsyncSessionLocal
    from src.shared.db.models import Source

    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Source.id).where(Source.enabled.is_(True)))
            source_ids = res.scalars().all()
            for sid in source_ids:
                await register_source_poller(sid)
    except Exception as exc:
        logger.error("init_all_source_pollers startup error: %s", exc)

async def init_all_live_sync_pollers() -> None:
    """Legacy alias for init_all_source_pollers."""
    await init_all_source_pollers()