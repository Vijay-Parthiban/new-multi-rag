import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.utils.paths import storage_root
from src.ingestion_service.clients.scraper import start_crawl_scrape_pipeline
from src.ingestion_service.core.indexer import FileIndexer, IndexContext, validate_pipeline_config
from src.ingestion_service.core.page_yielder import iter_file_pages
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE
from src.shared.config.settings import get_settings
from src.shared.db.models import FileRecord, FileStatus, IndexModality, JobStatus, Pipeline, PipelineRun, IndexedFile

logger = logging.getLogger(__name__)


async def run_pipeline_job(db: AsyncSession, run_id: uuid.UUID) -> None:
    """
    Executes a complete ingestion pipeline run asynchronously in the worker background.
    
    Orchestrates the entire end-to-end embedding generation by:
    1. Validating pipeline configurations.
    2. Instantiating a scraper pipeline via API if `web_scraper_enabled` is active.
    3. Resolving newly synced local files that haven't been hashed and embedded yet.
    4. Dynamically extracting and indexing (to Qdrant) multimodal sources block-by-block.
    
    Args:
        db: Active SQLAlchemy AsyncSession.
        run_id: DB primary key for the target PipelineRun record.
    """
    run = await db.get(PipelineRun, run_id, options=(selectinload(PipelineRun.pipeline),))
    if not run or run.status not in {JobStatus.PENDING, JobStatus.PROCESSING}:
        return

    pipeline = run.pipeline
    try:
        validate_pipeline_config(pipeline)
    except ValueError as exc:
        await _fail_run(db, run, str(exc))
        return

    run.status = JobStatus.PROCESSING
    run.started_at = datetime.now(UTC)
    await db.commit()

    collection = pipeline.qdrant_collection
    ctx = IndexContext(pipeline=pipeline, run_id=run.id, collection=collection)

    try:
        if pipeline.web_scraper_enabled:
            embedding_source = "markdown" if pipeline.modality != IndexModality.IMAGE else "image"
            from src.ingestion_service.core.indexer import _resolve_modality, _use_sparse

            modality = _resolve_modality(pipeline)
            scraper_result = await start_crawl_scrape_pipeline(
                seed_url=pipeline.scraper_seed_url or "",
                max_depth=pipeline.scraper_max_depth,
                max_pages=pipeline.scraper_max_pages,
                mode=pipeline.scraper_mode,
                embedding_source=embedding_source,
                qdrant_collection=pipeline.qdrant_collection,
                embedding_model=pipeline.embedding_model,
                sparse_embedding_model=pipeline.sparse_embedding_model,
                pipeline_description=pipeline.description,
                use_sparse=_use_sparse(pipeline.rag_strategy, modality),
            )
            crawl = scraper_result.get("crawl_job") or {}
            scrape = scraper_result.get("scrape_job") or {}
            run.scraper_crawl_job_id = str(crawl.get("id", "")) or None
            run.scraper_scrape_job_id = str(scrape.get("id", "")) if scrape else None
            await db.commit()

        # Get currently indexed hashes so we don't duplicate on manual manual runs
        indexed_res = await db.execute(select(IndexedFile).where(IndexedFile.pipeline_id == pipeline.id))
        indexed_hashes = {rec.content_hash for rec in indexed_res.scalars().all()}

        files = await _load_synced_files(db, pipeline)
        
        truly_new_files = []
        for file_record in files:
            if file_record.content_hash and file_record.content_hash in indexed_hashes:
                continue
            truly_new_files.append(file_record)

        run.files_total = len(truly_new_files)
        await db.commit()

        indexer = FileIndexer(ctx)
        for file_record in truly_new_files:
            path = storage_root() / (file_record.relative_path or "")
            if not path.exists():
                logger.warning("File missing on disk: %s", path)
                run.files_processed += 1
                await db.commit()
                continue

            directory_name = file_record.directory.name if file_record.directory else "unknown"

            def _process_file() -> tuple[int, int]:
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

            pages_indexed, points = await asyncio.to_thread(_process_file)
            
            # Record it so the cronjob knows it's already indexed
            if file_record.content_hash:
                db.add(IndexedFile(
                    pipeline_id=pipeline.id,
                    file_id=file_record.id,
                    content_hash=file_record.content_hash
                ))
            
            run.files_processed += 1
            run.pages_indexed += pages_indexed
            run.points_upserted += points
            await db.commit()
            logger.info(
                "pipeline_file_indexed run=%s file=%s pages=%d points=%d",
                run.id,
                file_record.original_name,
                pages_indexed,
                points,
            )

        run.status = JobStatus.SUCCESS
        run.completed_at = datetime.now(UTC)
        run.error_message = None
        await db.commit()
        logger.info(
            "pipeline_run_complete run=%s files=%d pages=%d points=%d source=%s",
            run.id,
            run.files_processed,
            run.pages_indexed,
            run.points_upserted,
            FILE_INGEST_SOURCE_TYPE,
        )
    except Exception as exc:
        logger.exception("pipeline_run_failed run=%s", run.id)
        await db.rollback()
        run = await db.get(PipelineRun, run_id)
        if run:
            await _fail_run(db, run, str(exc))


async def _load_synced_files(db: AsyncSession, pipeline: Pipeline) -> list[FileRecord]:
    from src.shared.db.models import Directory
    from src.shared.storage.s3_client import get_object, list_objects
    import hashlib

    all_files: list[FileRecord] = []

    # 1. Directory-based local files
    if pipeline.directory_names:
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
        allowed = {str(n).lower() for n in pipeline.directory_names}
        all_files.extend([f for f in files if f.directory and f.directory.name.lower() in allowed])

    # 2. Source MinIO buckets linked to pipeline
    await pipeline.awaitable_attrs.sources
    pipeline_sources = pipeline.sources or []
    sources_to_check = []
    for ps in pipeline_sources:
        await ps.awaitable_attrs.source
        if ps.source:
            sources_to_check.append(ps.source)
    if not sources_to_check:
        res_s = await db.execute(select(Source).where(Source.enabled.is_(True)))
        sources_to_check = list(res_s.scalars().all())

    for source in sources_to_check:
        if not source or not source.minio_bucket:
            continue
        bucket = source.minio_bucket
        objs = await list_objects(bucket)
        if not objs:
            continue

        dir_res = await db.execute(select(Directory).where(Directory.name == source.name))
        dir_obj = dir_res.scalar_one_or_none()
        if not dir_obj:
            dir_obj = Directory(id=uuid.uuid4(), name=source.name)
            db.add(dir_obj)
            await db.commit()

        for obj in objs:
            key = obj.key
            if not key or key.endswith("/"):
                continue

            content = await get_object(bucket, key)
            if not content:
                continue

            filename = Path(key).name
            rel_dir = Path("minio_sources") / bucket
            dest_dir = storage_root() / rel_dir
            dest_dir.mkdir(parents=True, exist_ok=True)

            file_path = dest_dir / filename
            with open(file_path, "wb") as f:
                f.write(content)

            content_hash = hashlib.sha256(content).hexdigest()
            rel_path = str(rel_dir / filename)

            f_res = await db.execute(
                select(FileRecord).where(
                    FileRecord.directory_id == dir_obj.id,
                    FileRecord.original_name == filename,
                )
            )
            rec = f_res.scalar_one_or_none()
            if not rec:
                rec = FileRecord(
                    id=uuid.uuid4(),
                    directory_id=dir_obj.id,
                    original_name=filename,
                    relative_path=rel_path,
                    mime_type="application/pdf" if filename.endswith(".pdf") else "application/octet-stream",
                    size_bytes=len(content),
                    content_hash=content_hash,
                    status=FileStatus.SYNCED,
                )
                db.add(rec)
                await db.commit()
            else:
                rec.content_hash = content_hash
                rec.relative_path = rel_path
                rec.status = FileStatus.SYNCED
                await db.commit()

            rec.directory = dir_obj
            all_files.append(rec)

    return all_files

async def _fail_run(db: AsyncSession, run: PipelineRun, message: str) -> None:
    run.status = JobStatus.FAILED
    run.error_message = message
    run.completed_at = datetime.now(UTC)
    await db.commit()
