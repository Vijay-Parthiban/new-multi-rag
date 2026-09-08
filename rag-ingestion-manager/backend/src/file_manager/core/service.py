import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core import chunks
from src.file_manager.core.duplicates import create_duplicate_record, find_duplicate_in_directory
from src.file_manager.core.errors import NotFoundError
from src.file_manager.core.storage import (
    create_append_file_job,
    create_upload_job,
    get_directory,
    get_or_create_directory,
)
from src.file_manager.utils.hashing import verify_stitched_hash
from src.shared.db.models import ChunkUpload, FileRecord, JobOperation
from src.shared.io import async_files


async def complete_chunk_upload(db: AsyncSession, upload_id: uuid.UUID) -> dict:
    upload = await db.get(ChunkUpload, upload_id)
    if not upload:
        raise NotFoundError("UPLOAD_NOT_FOUND", "Chunk upload session not found.")

    stitched = await chunks.stitch_chunks(upload)
    try:
        mime_type = await chunks.validate_staged_file(stitched, upload.file_name)
        content_hash = await asyncio.to_thread(
            verify_stitched_hash, stitched, upload.client_content_hash or ""
        )

        if upload.operation == JobOperation.APPEND and upload.target_file_id:
            target = await db.get(
                FileRecord,
                upload.target_file_id,
                options=(selectinload(FileRecord.directory),),
            )
            if not target:
                raise NotFoundError("FILE_NOT_FOUND", "Append target file not found.")
            directory = target.directory
            job_id = uuid.uuid4()
            staged = await chunks.finalize_to_staging(stitched, job_id, upload.file_name)
            job = await create_append_file_job(
                db,
                directory=directory,
                target=target,
                staged_path=staged,
                append_size=upload.total_size,
            )
            result = {
                "file_id": str(target.id),
                "job_id": str(job.id),
                "status": "processing",
                "content_hash": content_hash,
                "client_content_hash": upload.client_content_hash,
                "hash_verified": True,
            }
        else:
            directory = await get_or_create_directory(db, upload.directory_name)
            if upload.operation == JobOperation.APPEND:
                await get_directory(db, upload.directory_name)

            existing = await find_duplicate_in_directory(db, directory.id, content_hash)
            if existing:
                duplicate = await create_duplicate_record(
                    db,
                    directory=directory,
                    original_name=upload.file_name,
                    mime_type=mime_type,
                    size_bytes=upload.total_size,
                    content_hash=content_hash,
                    client_content_hash=upload.client_content_hash,
                    existing=existing,
                )
                result = {
                    "file_id": str(duplicate.id),
                    "job_id": None,
                    "status": "duplicate",
                    "content_hash": content_hash,
                    "client_content_hash": upload.client_content_hash,
                    "hash_verified": True,
                    "duplicate_of_file_id": str(existing.id),
                    "duplicate_of_file_name": existing.original_name,
                }
            else:
                job_id = uuid.uuid4()
                staged = await chunks.finalize_to_staging(stitched, job_id, upload.file_name)
                file_record, job = await create_upload_job(
                    db,
                    directory=directory,
                    original_name=upload.file_name,
                    staged_path=staged,
                    mime_type=mime_type,
                    size_bytes=upload.total_size,
                    content_hash=content_hash,
                    client_content_hash=upload.client_content_hash,
                )
                result = {
                    "file_id": str(file_record.id),
                    "job_id": str(job.id),
                    "status": "processing",
                    "content_hash": content_hash,
                    "client_content_hash": upload.client_content_hash,
                    "hash_verified": True,
                }

        await chunks.cleanup_temp(upload_id)
        await db.delete(upload)
        await db.commit()
        return result
    except Exception:
        await async_files.unlink(stitched, missing_ok=True)
        await chunks.cleanup_temp(upload_id)
        raise
