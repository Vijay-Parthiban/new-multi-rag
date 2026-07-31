import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core.duplicates import assert_no_duplicate_in_directory
from src.file_manager.core.errors import NotFoundError, ValidationError
from src.shared.config.settings import get_settings
from src.shared.db.models import FileRecord, FileStatus, JobOperation, JobStatus, SyncJob
from src.shared.io import async_files
from src.shared.storage.s3_client import (
    delete_object,
    get_object,
    put_object,
)


async def _upload_to_s3(bucket: str, key: str, local_path: Path) -> None:
    """Upload a local file to S3."""
    data = await async_files.read_bytes(local_path)
    await put_object(bucket, key, data)


async def _download_from_s3(bucket: str, key: str, local_path: Path) -> None:
    """Download an S3 object to a local path."""
    data = await get_object(bucket, key)
    await async_files.write_bytes(local_path, data)


async def process_upload_job(db: AsyncSession, job: SyncJob) -> None:
    file_record = await db.get(
        FileRecord, job.file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File record missing for upload job.")

    directory = file_record.directory
    staged = Path(job.payload["staged_path"])
    if not await async_files.path_exists(staged):
        raise FileNotFoundError(f"Staged file missing: {staged}")

    stored_name = job.payload.get(
        "stored_name",
        str(uuid.uuid4().hex[:12]) + "-" + job.payload["original_name"],
    )
    key = f"uploads/{directory.name}/{stored_name}"
    settings = get_settings()
    bucket = f"{settings.minio_bucket_prefix}-{directory.name}"

    await _upload_to_s3(bucket, key, staged)

    file_record.stored_name = stored_name
    file_record.relative_path = key
    file_record.mime_type = job.payload.get("mime_type")
    file_record.size_bytes = job.payload.get("size_bytes", 0) or await async_files.stat_size(staged)
    file_record.content_hash = job.payload.get("content_hash") or file_record.content_hash
    file_record.status = FileStatus.SYNCED
    file_record.error_message = None


async def process_append_job(db: AsyncSession, job: SyncJob) -> None:
    file_record = await db.get(
        FileRecord, job.file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File record missing for append job.")

    target_key = job.payload["target_relative_path"]
    staged = Path(job.payload["staged_path"])

    if not await async_files.path_exists(staged):
        raise FileNotFoundError(f"Staged append data missing: {staged}")

    directory = file_record.directory
    bucket = f"{get_settings().minio_bucket_prefix}-{directory.name}"

    # Download existing, append staged data, upload back
    existing_data = await get_object(bucket, target_key)
    append_data = await async_files.read_bytes(staged)
    combined = existing_data + append_data
    await put_object(bucket, target_key, combined)

    # Compute hash of combined content
    new_hash = hashlib.sha256(combined).hexdigest()
    await assert_no_duplicate_in_directory(
        db,
        file_record.directory_id,
        new_hash,
        exclude_file_id=file_record.id,
    )

    file_record.size_bytes = len(combined)
    file_record.content_hash = new_hash
    file_record.status = FileStatus.SYNCED
    file_record.error_message = None


async def process_rename_job(db: AsyncSession, job: SyncJob) -> None:
    file_record = await db.get(
        FileRecord, job.file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record:
        raise NotFoundError("FILES_NOT_FOUND", "File record missing for rename job.")
    if not file_record.relative_path:
        raise ValidationError("NO_STORED_FILE", "File has no stored path.")

    new_name = job.payload["new_name"]
    old_key = file_record.relative_path

    prefix = (
        file_record.stored_name.split("-", 1)[0]
        if file_record.stored_name else uuid.uuid4().hex[:12]
    )
    new_stored = f"{prefix}-{new_name}"
    directory_name = file_record.directory.name
    new_key = f"uploads/{directory_name}/{new_stored}"

    bucket = f"{get_settings().minio_bucket_prefix}-{directory_name}"

    # Copy to new key, then delete old (S3 has no rename)
    data = await get_object(bucket, old_key)
    await put_object(bucket, new_key, data)
    await delete_object(bucket, old_key)

    file_record.original_name = new_name
    file_record.stored_name = new_stored
    file_record.relative_path = new_key
    file_record.status = FileStatus.SYNCED
    file_record.error_message = None


async def process_delete_job(db: AsyncSession, job: SyncJob) -> None:
    file_record = await db.get(
        FileRecord, job.file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File record missing for delete job.")

    if file_record.relative_path:
        bucket = f"{get_settings().minio_bucket_prefix}-{file_record.directory.name}"
        try:
            await delete_object(bucket, file_record.relative_path)
        except Exception:
            pass  # already gone is fine

    file_record.status = FileStatus.DELETED
    file_record.error_message = None


async def _cleanup_staging(staged_path: str | None) -> None:
    """Clean up local staging files after job completion."""
    if not staged_path:
        return
    path = Path(staged_path)
    if await async_files.path_exists(path):
        await async_files.unlink(path)
    parent = path.parent
    if await async_files.path_exists(parent):
        has_files = await asyncio.to_thread(any, parent.iterdir())
        if not has_files:
            await asyncio.to_thread(parent.rmdir)


async def mark_job_failed(db: AsyncSession, job: SyncJob, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error_message = error
    job.completed_at = datetime.now(UTC)

    if job.file_id and job.operation != JobOperation.DELETE:
        file_record = await db.get(FileRecord, job.file_id)
        if file_record:
            file_record.status = FileStatus.FAILED
            file_record.error_message = error
    await db.commit()


async def run_job(db: AsyncSession, job_id: uuid.UUID) -> None:
    job = await db.get(SyncJob, job_id)
    if not job or job.status not in {JobStatus.PENDING, JobStatus.PROCESSING}:
        return

    job.status = JobStatus.PROCESSING
    await db.commit()

    try:
        if job.operation == JobOperation.UPLOAD:
            await process_upload_job(db, job)
        elif job.operation == JobOperation.APPEND:
            await process_append_job(db, job)
        elif job.operation == JobOperation.RENAME:
            await process_rename_job(db, job)
        elif job.operation == JobOperation.DELETE:
            await process_delete_job(db, job)
        else:
            raise ValueError("UNKNOWN_OPERATION", f"Unknown operation: {job.operation}")

        job.status = JobStatus.SUCCESS
        job.error_message = None
        job.completed_at = datetime.now(UTC)
        await db.commit()
        await _cleanup_staging(job.payload.get("staged_path"))
    except Exception as exc:
        await db.rollback()
        job = await db.get(SyncJob, job_id)
        if job:
            await mark_job_failed(db, job, str(exc))