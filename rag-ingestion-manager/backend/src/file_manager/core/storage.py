import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.file_manager.core.errors import ConflictError, NotFoundError
from src.file_manager.core.validator import validate_file_name
from src.file_manager.utils.paths import sanitize_directory_name
from src.shared.db.models import (
    Directory,
    FileRecord,
    FileStatus,
    JobOperation,
    JobStatus,
    SyncJob,
)
from src.shared.queue.client import enqueue_job


async def get_or_create_directory(db: AsyncSession, name: str) -> Directory:
    safe = sanitize_directory_name(name)
    result = await db.execute(select(Directory).where(Directory.name == safe))
    directory = result.scalar_one_or_none()
    if directory:
        return directory
    directory = Directory(name=safe)
    db.add(directory)
    await db.flush()
    return directory


async def get_directory(db: AsyncSession, name: str) -> Directory:
    safe = sanitize_directory_name(name)
    result = await db.execute(select(Directory).where(Directory.name == safe))
    directory = result.scalar_one_or_none()
    if not directory:
        raise NotFoundError("DIRECTORY_NOT_FOUND", "Directory not found.", {"name": safe})
    return directory


async def create_upload_job(
    db: AsyncSession,
    *,
    directory: Directory,
    original_name: str,
    staged_path: Path,
    mime_type: str,
    size_bytes: int,
    content_hash: str,
    client_content_hash: str | None = None,
) -> tuple[FileRecord, SyncJob]:
    file_record = FileRecord(
        directory_id=directory.id,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        client_content_hash=client_content_hash,
        hash_verified=True,
        status=FileStatus.PROCESSING,
    )
    db.add(file_record)
    await db.flush()

    job = SyncJob(
        directory_id=directory.id,
        file_id=file_record.id,
        operation=JobOperation.UPLOAD,
        payload={
            "staged_path": str(staged_path),
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
        },
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(file_record)
    await db.refresh(job)
    await enqueue_job(job.id)
    return file_record, job


async def create_append_file_job(
    db: AsyncSession,
    *,
    directory: Directory,
    target: FileRecord,
    staged_path: Path,
    append_size: int,
) -> SyncJob:
    if target.status == FileStatus.DELETED:
        raise ConflictError("FILE_DELETED", "Cannot append to a deleted file.")
    if not target.relative_path:
        raise ConflictError("FILE_NOT_SYNCED", "Target file is not synced yet.")

    target.status = FileStatus.PROCESSING
    job = SyncJob(
        directory_id=directory.id,
        file_id=target.id,
        operation=JobOperation.APPEND,
        payload={
            "staged_path": str(staged_path),
            "target_relative_path": target.relative_path,
            "append_size": append_size,
        },
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await enqueue_job(job.id)
    return job


async def request_rename(db: AsyncSession, file_id: uuid.UUID, new_name: str) -> SyncJob:
    safe_name = validate_file_name(new_name)
    file_record = await db.get(FileRecord, file_id)
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File not found.", {"file_id": str(file_id)})
    if file_record.status == FileStatus.DELETED:
        raise ConflictError("FILE_DELETED", "Cannot rename a deleted file.")
    if file_record.status in {FileStatus.PROCESSING, FileStatus.DUPLICATE}:
        raise ConflictError("FILE_NOT_RENAMEABLE", "This file cannot be renamed.")

    file_record.status = FileStatus.PROCESSING
    job = SyncJob(
        directory_id=file_record.directory_id,
        file_id=file_record.id,
        operation=JobOperation.RENAME,
        payload={"new_name": safe_name},
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await enqueue_job(job.id)
    return job


async def request_delete(db: AsyncSession, file_id: uuid.UUID) -> SyncJob:
    file_record = await db.get(FileRecord, file_id)
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File not found.", {"file_id": str(file_id)})
    if file_record.status == FileStatus.DELETED:
        raise ConflictError("ALREADY_DELETED", "File is already deleted.")

    file_record.status = FileStatus.PROCESSING
    job = SyncJob(
        directory_id=file_record.directory_id,
        file_id=file_record.id,
        operation=JobOperation.DELETE,
        payload={},
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await enqueue_job(job.id)
    return job
