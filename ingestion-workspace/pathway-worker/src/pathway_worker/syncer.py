"""Source syncer — polls DB for enabled sources, runs Airbyte syncs, triggers RAG re-index.

This is the main orchestrator that:
1. Polls the ingestion-backend DB for enabled Source records
2. Runs Airbyte connector syncs, writing output to per-source MinIO buckets
3. Records FileRecord entries for each synced file
4. Enqueues pipeline sync jobs on Redis for linked pipelines
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pathway_worker.airbyte_runner import run_connector_sync
from pathway_worker.settings import get_settings

logger = logging.getLogger(__name__)

# ── Schema constants (matches ingestion-backend models) ───────────────

SOURCE_CONNECTOR_LIVE = "live"
SOURCE_STATUS_DISCONNECTED = "disconnected"
SOURCE_STATUS_CONNECTED = "connected"
SOURCE_STATUS_ERROR = "error"


# ── DB imports (lazy — must have ingestion-backend in path) ───────────

async def _get_db_session() -> AsyncSession:
    """Create a new async DB session using the shared session factory."""
    from src.shared.db.session import AsyncSessionLocal

    return AsyncSessionLocal()


def _make_bucket_name(source_id: uuid.UUID, name: str) -> str:
    """Generate the MinIO bucket name for a source."""
    settings = get_settings()
    safe_name = name.lower().replace(" ", "-").replace("_", "-")
    short_id = str(source_id)[:8]
    return f"{settings.minio_bucket_prefix}-{safe_name}-{short_id}"


# ── Redis queue helpers ───────────────────────────────────────────────


async def _enqueue_rag_sync(pipeline_id: uuid.UUID) -> None:
    """Trigger RAG re-indexing for a linked pipeline."""
    import json

    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.lpush(
            settings.sync_queue,
            json.dumps({"pipeline_id": str(pipeline_id)}),
        )
        logger.info("rag_sync_queued pipeline=%s", pipeline_id)
    finally:
        await client.aclose()


# ── Main sync loop ────────────────────────────────────────────────────

async def _sync_one_source(
    db: AsyncSession,
    source_id: uuid.UUID,
) -> bool:
    """Sync a single source. Returns True on success."""
    from src.shared.db.models import FileRecord, FileStatus, PipelineSource, Source, Directory

    source = await db.get(Source, source_id)
    if not source or not source.enabled:
        return False

    logger.info(
        "syncing_source id=%s name=%s type=%s",
        source.id, source.name, source.connector_type,
    )

    try:
        files_written = await run_connector_sync(
            source_id=source.id,
            connector_type=source.connector_type,
            config=source.config,
            bucket=source.minio_bucket,
            output_dir=None,  # not used with direct S3 output
        )

        if files_written > 0:
            # List newly written files in the bucket
            from src.shared.storage import list_objects as s3_list

            synced_objects = await s3_list(
                source.minio_bucket,
                prefix=f"pathway-syncs/{str(source.id)}/",
            )

            for obj in synced_objects:
                # Create a FileRecord for each synced object
                content_hash = hashlib.sha256(obj.key.encode()).hexdigest()
                file_record = FileRecord(
                    original_name=obj.key.rsplit("/", 1)[-1],
                    stored_name=obj.key.rsplit("/", 1)[-1],
                    relative_path=obj.key,
                    mime_type="application/json",
                    size_bytes=obj.size,
                    content_hash=content_hash,
                    status=FileStatus.SYNCED,
                )
                # We need a directory for the FileRecord — use source's name
                # Find or create directory for this source
                dir_name = source.name.lower().replace(" ", "-")
                dir_result = await db.execute(
                    select(Directory).where(Directory.name == dir_name)
                )
                directory = dir_result.scalar_one_or_none()
                if not directory:
                    directory = Directory(name=dir_name)
                    db.add(directory)
                    await db.flush()

                file_record.directory_id = directory.id
                db.add(file_record)

            await db.commit()

            # Update source sync timestamp
            source.last_sync_at = datetime.now(UTC)
            source.status = SOURCE_STATUS_CONNECTED
            source.error_message = None
            await db.commit()

            # Trigger RAG indexing for all linked pipelines
            linked = await db.execute(
                select(PipelineSource).where(PipelineSource.source_id == source.id)
            )
            for link in linked.scalars().all():
                await _enqueue_rag_sync(link.pipeline_id)

        return files_written > 0

    except Exception as exc:
        logger.exception("source_sync_failed id=%s name=%s", source.id, source.name)
        source.status = SOURCE_STATUS_ERROR
        source.error_message = str(exc)
        await db.commit()
        return False


async def sync_all_sources() -> None:
    """Poll the Source table and sync each enabled source that's ready."""
    from src.shared.db.models import Source, SourceMonitorMode

    logger.info("source_sync_poll_start")

    try:
        async with _get_db_session() as db:
            result = await db.execute(
                select(Source).where(
                    Source.enabled.is_(True),
                    Source.status != SOURCE_STATUS_ERROR,
                )
            )
            sources = result.scalars().all()
    except Exception as e:
        logger.error("db_connection_failed: %s", e)
        return

    if not sources:
        logger.info("source_sync_poll_no_sources")
        return

    # Sort: scheduled sources go first (if due), then live ones
    now = datetime.now(UTC)
    sync_queue: list[Source] = []

    for source in sources:
        if source.monitor_mode == SourceMonitorMode.LIVE:
            sync_queue.append(source)
        elif source.monitor_mode == SourceMonitorMode.SCHEDULED:
            if source.sync_interval_minutes is None:
                continue
            if source.last_sync_at is None:
                sync_queue.append(source)
            else:
                elapsed = (now - source.last_sync_at).total_seconds() / 60.0
                if elapsed >= source.sync_interval_minutes:
                    sync_queue.append(source)

    if not sync_queue:
        logger.info("source_sync_poll_nothing_due")
        return

    settings = get_settings()
    semaphore = asyncio.Semaphore(settings.max_concurrent_syncs)

    async def _sync_with_limit(source: Source) -> None:
        async with semaphore:
            try:
                async with _get_db_session() as db:
                    await _sync_one_source(db, source.id)
            except Exception:
                logger.exception(
                    "sync_one_source_failed id=%s name=%s",
                    source.id, source.name,
                )

    tasks = [_sync_with_limit(s) for s in sync_queue]
    await asyncio.gather(*tasks)

    logger.info("source_sync_poll_complete processed=%d", len(sync_queue))


# ── Continuous background loop ────────────────────────────────────────

async def run_source_sync_loop() -> None:
    """Continuously poll and sync sources on a configurable interval."""
    settings = get_settings()
    logger.info(
        "source_sync_loop_starting interval=%ds",
        settings.source_poll_interval_sec,
    )

    while True:
        try:
            await sync_all_sources()
        except Exception:
            logger.exception("source_sync_loop_error")
        await asyncio.sleep(settings.source_poll_interval_sec)