"""Sync runner — reconcile pipeline's indexed files with current folder state.

Compares tracked IndexedFile records (by content_hash) against current SYNCED
files on disk.  Indexes new/changed files, deletes Qdrant chunks for removed
files, and updates the IndexedFile tracking table.
"""

import asyncio
import logging
from pathlib import Path
import uuid
from datetime import datetime, UTC
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
    PipelineSource,
    Source,
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


async def _load_synced_source_files(source: Source) -> list[dict]:
    """Return object metadata dicts for objects stored in the source's MinIO bucket."""
    if not source.minio_bucket:
        return []
    from src.shared.storage.s3_client import list_objects
    try:
        objs = await list_objects(source.minio_bucket)
    except Exception as exc:
        logger.error("failed_listing_minio_bucket bucket=%s err=%s", source.minio_bucket, exc)
        return []

    res = []
    for obj in objs:
        if not obj.key or obj.key.endswith("/"):
            continue
        content_hash = obj.etag if obj.etag else f"{obj.size}-{obj.last_modified}"
        original_name = Path(obj.key).name
        virtual_file_id = uuid.uuid5(uuid.NAMESPACE_URL, f"minio://{source.id}/{obj.key}")
        res.append({
            "source_id": source.id,
            "source_name": source.name,
            "bucket_name": source.minio_bucket,
            "file_key": obj.key,
            "original_name": original_name,
            "content_hash": content_hash,
            "size": obj.size,
            "virtual_file_id": virtual_file_id,
        })
    return res

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
    pipeline = await db.get(
        Pipeline,
        pipeline_id,
        options=(
            selectinload(Pipeline.runs),
            selectinload(Pipeline.sources).selectinload(PipelineSource.source),
        ),
    )
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
            rec.file_id: rec for rec in indexed_records if rec.file_id
        }
        indexed_by_source_key: dict[tuple[uuid.UUID, str], IndexedFile] = {
            (rec.source_id, rec.file_key): rec
            for rec in indexed_records
            if rec.source_id and rec.file_key
        }
        indexed_hashes: set[str] = {rec.content_hash for rec in indexed_records if rec.content_hash}

        # 3. Determine what to do for directory-backed files
        new_files = [
            f for f in current_files
            if f.content_hash
            and f.content_hash not in indexed_hashes
            and f.id not in indexed_by_file_id
        ]

        changed_files = [
            f for f in current_files
            if f.id in indexed_by_file_id
            and f.content_hash
            and indexed_by_file_id[f.id].content_hash != f.content_hash
        ]

        deleted_indexed = [
            rec for rec in indexed_records
            if rec.file_id and rec.file_id not in current_by_id
        ]

        # 3b. Determine what to do for source-backed files in linked MinIO buckets
        current_source_objs: list[dict] = []
        if pipeline.sources:
            for ps in pipeline.sources:
                if ps.source:
                    objs = await _load_synced_source_files(ps.source)
                    current_source_objs.extend(objs)

        current_source_by_key: dict[tuple[uuid.UUID, str], dict] = {
            (obj["source_id"], obj["file_key"]): obj for obj in current_source_objs
        }

        new_source_objs = [
            obj for obj in current_source_objs
            if (obj["source_id"], obj["file_key"]) not in indexed_by_source_key
            and obj["content_hash"] not in indexed_hashes
        ]

        changed_source_objs = [
            obj for obj in current_source_objs
            if (obj["source_id"], obj["file_key"]) in indexed_by_source_key
            and indexed_by_source_key[(obj["source_id"], obj["file_key"])].content_hash != obj["content_hash"]
        ]

        deleted_source_indexed = [
            rec for rec in indexed_records
            if rec.source_id and rec.file_key and (rec.source_id, rec.file_key) not in current_source_by_key
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
        truly_new_source_objs: list[dict] = []
        for obj in new_source_objs:
            if obj["content_hash"] in indexed_hashes:
                logger.info(
                    "sync_skip_duplicate_source pipeline=%s key=%s hash=%s",
                    pipeline.id, obj["file_key"], obj["content_hash"],
                )
                continue
            truly_new_source_objs.append(obj)
            indexed_hashes.add(obj["content_hash"])

        run.files_total = (
            len(truly_new_files)
            + len(changed_files)
            + len(deleted_indexed)
            + len(truly_new_source_objs)
            + len(changed_source_objs)
            + len(deleted_source_indexed)
        )
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

        # 4d. Index NEW source files
        for source_obj in truly_new_source_objs:
            pages_indexed, points = await _index_single_source_file(indexer, source_obj)
            db.add(IndexedFile(
                pipeline_id=pipeline.id,
                source_id=source_obj["source_id"],
                file_key=source_obj["file_key"],
                content_hash=source_obj["content_hash"],
            ))
            run.files_processed += 1
            run.pages_indexed += pages_indexed
            run.points_upserted += points
            await db.commit()
            logger.info(
                "sync_indexed_new_source pipeline=%s source=%s key=%s pages=%d points=%d",
                pipeline.id, source_obj["source_name"], source_obj["file_key"], pages_indexed, points,
            )
        # 4e. Re-index CHANGED source files
        for source_obj in changed_source_objs:
            filt = _build_file_filter(file_id=source_obj["virtual_file_id"], pipeline_id=pipeline.id)
            await asyncio.to_thread(store.delete_by_filter, filt)

            pages_indexed, points = await _index_single_source_file(indexer, source_obj)
            idx_rec = indexed_by_source_key[(source_obj["source_id"], source_obj["file_key"])]
            idx_rec.content_hash = source_obj["content_hash"]
            idx_rec.indexed_at = datetime.now(UTC)

            run.files_processed += 1
            run.pages_indexed += pages_indexed
            run.points_upserted += points
            await db.commit()
            logger.info(
                "sync_reindexed_changed_source pipeline=%s source=%s key=%s pages=%d points=%d",
                pipeline.id, source_obj["source_name"], source_obj["file_key"], pages_indexed, points,
            )

        # 4f. Delete chunks for REMOVED source files
        for idx_rec in deleted_source_indexed:
            v_id = uuid.uuid5(uuid.NAMESPACE_URL, f"minio://{idx_rec.source_id}/{idx_rec.file_key}")
            filt = _build_file_filter(file_id=v_id, pipeline_id=pipeline.id)
            await asyncio.to_thread(store.delete_by_filter, filt)
            await db.execute(
                delete(IndexedFile).where(IndexedFile.id == idx_rec.id)
            )
            run.files_processed += 1
            await db.commit()
            logger.info(
                "sync_deleted_source pipeline=%s source_id=%s file_key=%s",
                pipeline.id, idx_rec.source_id, idx_rec.file_key,
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

async def _index_single_source_file(indexer: FileIndexer, source_obj: dict) -> tuple[int, int]:
    """Download source object from MinIO to temporary file and index its pages."""
    import mimetypes
    import tempfile
    from src.shared.storage.s3_client import get_object

    bucket_name = source_obj["bucket_name"]
    file_key = source_obj["file_key"]
    original_name = source_obj["original_name"]
    virtual_file_id = source_obj["virtual_file_id"]
    source_name = source_obj["source_name"]

    data = await get_object(bucket_name, file_key)
    suffix = Path(original_name).suffix or ".bin"
    mime_type, _ = mimetypes.guess_type(original_name)
    if not mime_type and suffix.lower() == ".pdf":
        mime_type = "application/pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        def _process() -> tuple[int, int]:
            pages = iter_file_pages(tmp_path, mime_type, original_name)
            return indexer.index_file(
                file_path=tmp_path,
                file_id=virtual_file_id,
                file_name=original_name,
                directory_name=source_name,
                mime_type=mime_type,
                relative_path=file_key,
                pages=pages,
            )

        return await asyncio.to_thread(_process)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


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
