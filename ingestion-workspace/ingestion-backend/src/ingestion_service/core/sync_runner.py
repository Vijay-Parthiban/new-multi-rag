"""Sync runner — reconcile pipeline's indexed files with current folder state.

Compares tracked IndexedFile records (by content_hash) against current SYNCED
files on disk.  Indexes new/changed files, deletes Qdrant chunks for removed
files, and updates the IndexedFile tracking table.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from qdrant_client.http import models as qmodels
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.ingestion_service.core.indexer import FileIndexer, IndexContext, validate_pipeline_config
from src.ingestion_service.core.page_yielder import iter_file_pages
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore
from src.file_manager.utils.paths import storage_root
from src.shared.config.settings import get_settings
from src.shared.db.models import (
    FileRecord,
    FileStatus,
    IndexedFile,
    JobStatus,
    Pipeline,
    PipelineRun,
)

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────

async def _load_synced_files(db: AsyncSession, directory_names: list) -> list[FileRecord]:
    """Return all SYNCED FileRecords belonging to the given directories."""
    if not directory_names:
        return []
    result = await db.execute(
        select(FileRecord)
        .join(FileRecord.directory)
        .where(
            FileRecord.status == FileStatus.SYNCED,
            FileRecord.relative_path.isnot(None),
        )
        .options(selectinload(FileRecord.directory))
    )
    files = result.scalars().all()
    allowed = {str(n).lower() for n in directory_names}
    return [f for f in files if f.directory and f.directory.name.lower() in allowed]


async def _load_indexed_files(db: AsyncSession, pipeline_id: uuid.UUID) -> list[IndexedFile]:
    result = await db.execute(
        select(IndexedFile).where(IndexedFile.pipeline_id == pipeline_id)
    )
    return list(result.scalars().all())


def _build_file_filter(*, file_id: uuid.UUID, pipeline_id: uuid.UUID) -> qmodels.Filter:
    """Build a Qdrant filter that matches points for a specific file in a pipeline."""
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="file_id",
                match=qmodels.MatchValue(value=str(file_id)),
            ),
            qmodels.FieldCondition(
                key="pipeline_id",
                match=qmodels.MatchValue(value=str(pipeline_id)),
            ),
        ]
    )


# ── main sync logic ─────────────────────────────────────────────────────

async def sync_pipeline(db: AsyncSession, pipeline_id: uuid.UUID) -> uuid.UUID:
    """Synchronise a single pipeline's Qdrant collection with its folders.

    Returns the PipelineRun.id tracking this sync operation.
    """
    pipeline = await db.get(Pipeline, pipeline_id, options=(selectinload(Pipeline.runs),))
    if not pipeline:
        raise ValueError(f"Pipeline {pipeline_id} not found")

    validate_pipeline_config(pipeline)

    # Create a run to track this sync
    run = PipelineRun(
        pipeline_id=pipeline.id,
        status=JobStatus.PROCESSING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    collection = pipeline.qdrant_collection
    settings = get_settings()
    store = QdrantVectorStore(
        url=settings.qdrant_url,
        collection=collection,
        api_key=settings.qdrant_api_key,
    )

    try:
        # 1. Current files on disk  (SYNCED + in pipeline's directories)
        current_files = await _load_synced_files(db, pipeline.directory_names)
        current_by_id: dict[uuid.UUID, FileRecord] = {f.id: f for f in current_files}
        current_hashes: set[str] = {
            f.content_hash for f in current_files if f.content_hash
        }

        # 2. Already-indexed records
        indexed_records = await _load_indexed_files(db, pipeline.id)
        indexed_by_file_id: dict[uuid.UUID, IndexedFile] = {
            rec.file_id: rec for rec in indexed_records
        }
        indexed_hashes: set[str] = {rec.content_hash for rec in indexed_records}

        # 3. Determine what to do
        # New files: content_hash not yet indexed
        new_files = [
            f for f in current_files
            if f.content_hash
            and f.content_hash not in indexed_hashes
            and f.id not in indexed_by_file_id
        ]

        # Changed files: same file_id exists but content_hash differs
        changed_files = [
            f for f in current_files
            if f.id in indexed_by_file_id
            and f.content_hash
            and indexed_by_file_id[f.id].content_hash != f.content_hash
        ]

        # Deleted: indexed file_ids not in current set
        deleted_indexed = [
            rec for rec in indexed_records
            if rec.file_id not in current_by_id
        ]

        # Also skip files whose content_hash already indexed under a different file_id
        # (duplicate content detection)
        truly_new_files: list[FileRecord] = []
        for f in new_files:
            if f.content_hash in indexed_hashes:
                logger.info(
                    "sync_skip_duplicate pipeline=%s file=%s hash=%s",
                    pipeline.id, f.original_name, f.content_hash,
                )
                continue
            truly_new_files.append(f)
            # Track hash so subsequent files in this batch with same hash are also skipped
            indexed_hashes.add(f.content_hash)

        run.files_total = len(truly_new_files) + len(changed_files) + len(deleted_indexed)
        await db.commit()

        ctx = IndexContext(pipeline=pipeline, run_id=run.id, collection=collection)
        indexer = FileIndexer(ctx)

        # 4a. Index NEW files
        for file_record in truly_new_files:
            pages_indexed, points = await _index_single_file(indexer, file_record)
            db.add(IndexedFile(
                pipeline_id=pipeline.id,
                file_id=file_record.id,
                content_hash=file_record.content_hash,
            ))
            run.files_processed += 1
            run.pages_indexed += pages_indexed
            run.points_upserted += points
            await db.commit()
            logger.info(
                "sync_indexed_new pipeline=%s file=%s pages=%d points=%d",
                pipeline.id, file_record.original_name, pages_indexed, points,
            )

        # 4b. Re-index CHANGED files (delete old chunks first)
        for file_record in changed_files:
            # Delete old chunks
            filt = _build_file_filter(file_id=file_record.id, pipeline_id=pipeline.id)
            await asyncio.to_thread(store.delete_by_filter, filt)

            # Re-index
            pages_indexed, points = await _index_single_file(indexer, file_record)

            # Update tracking record
            idx_rec = indexed_by_file_id[file_record.id]
            idx_rec.content_hash = file_record.content_hash
            idx_rec.indexed_at = datetime.now(UTC)

            run.files_processed += 1
            run.pages_indexed += pages_indexed
            run.points_upserted += points
            await db.commit()
            logger.info(
                "sync_reindexed_changed pipeline=%s file=%s pages=%d points=%d",
                pipeline.id, file_record.original_name, pages_indexed, points,
            )

        # 4c. Delete chunks for REMOVED files
        for idx_rec in deleted_indexed:
            filt = _build_file_filter(file_id=idx_rec.file_id, pipeline_id=pipeline.id)
            await asyncio.to_thread(store.delete_by_filter, filt)
            await db.execute(
                delete(IndexedFile).where(IndexedFile.id == idx_rec.id)
            )
            run.files_processed += 1
            await db.commit()
            logger.info(
                "sync_deleted pipeline=%s file_id=%s", pipeline.id, idx_rec.file_id,
            )

        # 5. Done
        run.status = JobStatus.SUCCESS
        run.completed_at = datetime.now(UTC)
        run.error_message = None
        await db.commit()
        logger.info(
            "sync_complete pipeline=%s new=%d changed=%d deleted=%d",
            pipeline.id, len(truly_new_files), len(changed_files), len(deleted_indexed),
        )

    except Exception as exc:
        logger.exception("sync_failed pipeline=%s", pipeline.id)
        await db.rollback()
        run = await db.get(PipelineRun, run.id)
        if run:
            run.status = JobStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = datetime.now(UTC)
            await db.commit()

    return run.id


async def _index_single_file(indexer: FileIndexer, file_record: FileRecord) -> tuple[int, int]:
    """Index a single file and return (pages_indexed, points_upserted)."""
    path = storage_root() / (file_record.relative_path or "")
    if not path.exists():
        logger.warning("sync_file_missing: %s", path)
        return 0, 0

    directory_name = file_record.directory.name if file_record.directory else "unknown"

    def _process() -> tuple[int, int]:
        pages = iter_file_pages(path, file_record.mime_type, file_record.original_name)
        return indexer.index_file(
            file_path=path,
            file_id=file_record.id,
            file_name=file_record.original_name,
            directory_name=directory_name,
            mime_type=file_record.mime_type,
            relative_path=file_record.relative_path,
            pages=pages,
        )

    return await asyncio.to_thread(_process)


# ── top-level: sync ALL pipelines (called by cron) ──────────────────────

async def sync_all_pipelines() -> None:
    """Run sync for every pipeline that has directory_names configured."""
    from src.shared.db.session import AsyncSessionLocal

    logger.info("sync_all_pipelines_start")

    # Retry DB connection with exponential backoff for DNS/startup resilience
    max_retries = 5
    pipelines = []
    for attempt in range(1, max_retries + 1):
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Pipeline))
                pipelines = result.scalars().all()
            break
        except Exception as exc:
            if attempt == max_retries:
                logger.error(
                    "sync_all_pipelines: DB unreachable after %d attempts",
                    max_retries,
                )
                raise
            wait = 2 ** attempt
            logger.warning(
                "sync_all_pipelines: DB not ready (attempt %d/%d), retrying in %ds: %s",
                attempt, max_retries, wait, exc,
            )
            await asyncio.sleep(wait)

    for pipeline in pipelines:
        if not pipeline.directory_names:
            continue
        try:
            async with AsyncSessionLocal() as db:
                await sync_pipeline(db, pipeline.id)
        except Exception:
            logger.exception("sync_all_failed pipeline=%s", pipeline.id)

    logger.info("sync_all_pipelines_complete count=%d", len(pipelines))
