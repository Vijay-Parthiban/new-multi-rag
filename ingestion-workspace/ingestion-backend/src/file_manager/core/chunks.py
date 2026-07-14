import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.file_manager.core.validator import validate_file_content, validate_file_name
from src.file_manager.utils.hashing import normalize_hash
from src.file_manager.utils.paths import sanitize_directory_name, staging_dir, temp_dir
from src.shared.db.models import ChunkUpload, JobOperation
from src.shared.io import async_files


async def init_chunk_upload(
    db: AsyncSession,
    *,
    directory_name: str,
    file_name: str,
    total_chunks: int,
    total_size: int,
    mime_type: str | None = None,
    client_content_hash: str | None = None,
    target_file_id: uuid.UUID | None = None,
    operation: JobOperation = JobOperation.UPLOAD,
) -> ChunkUpload:
    if total_chunks < 1:
        raise ValidationError("INVALID_CHUNK_COUNT", "total_chunks must be at least 1.")
    if total_size < 1:
        raise ValidationError("INVALID_FILE_SIZE", "total_size must be at least 1 byte.")
    if not client_content_hash:
        raise ValidationError("MISSING_CONTENT_HASH", "client_content_hash is required.")

    safe_client_hash = normalize_hash(client_content_hash)
    safe_dir = sanitize_directory_name(directory_name)
    safe_name = validate_file_name(file_name)

    upload = ChunkUpload(
        directory_name=safe_dir,
        file_name=safe_name,
        total_chunks=total_chunks,
        total_size=total_size,
        mime_type=mime_type,
        client_content_hash=safe_client_hash,
        target_file_id=target_file_id,
        operation=operation,
        received_chunks=[],
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    await async_files.mkdir(temp_dir(upload.id))
    return upload


async def save_chunk(
    upload_id: uuid.UUID, chunk_index: int, data: bytes, db: AsyncSession
) -> ChunkUpload:
    upload = await db.get(ChunkUpload, upload_id)
    if not upload:
        raise NotFoundError("UPLOAD_NOT_FOUND", "Chunk upload session not found.", {"upload_id": str(upload_id)})

    if chunk_index < 0 or chunk_index >= upload.total_chunks:
        raise ValidationError(
            "INVALID_CHUNK_INDEX",
            f"chunk_index must be between 0 and {upload.total_chunks - 1}.",
            {"chunk_index": chunk_index},
        )

    chunk_path = temp_dir(upload_id) / f"chunk_{chunk_index:06d}"
    await async_files.write_bytes(chunk_path, data)

    received = set(upload.received_chunks or [])
    received.add(chunk_index)
    upload.received_chunks = sorted(received)
    await db.commit()
    await db.refresh(upload)
    return upload


async def stitch_chunks(upload: ChunkUpload) -> Path:
    received = set(upload.received_chunks or [])
    expected = set(range(upload.total_chunks))
    if received != expected:
        missing = sorted(expected - received)
        raise ConflictError(
            "INCOMPLETE_UPLOAD",
            "Not all chunks have been uploaded yet.",
            {"missing_chunks": missing},
        )

    upload_temp = temp_dir(upload.id)
    stitched = upload_temp / "stitched"
    chunk_paths = [upload_temp / f"chunk_{i:06d}" for i in range(upload.total_chunks)]

    for i, chunk_path in enumerate(chunk_paths):
        if not await async_files.path_exists(chunk_path):
            raise ConflictError(
                "MISSING_CHUNK_FILE",
                f"Chunk file {i} is missing on disk.",
                {"chunk_index": i},
            )

    written = await async_files.stitch_files(chunk_paths, stitched)
    if written != upload.total_size:
        raise ValidationError(
            "SIZE_MISMATCH",
            "Stitched file size does not match declared total_size.",
            {"expected": upload.total_size, "actual": written},
        )

    return stitched


async def finalize_to_staging(stitched: Path, job_id: uuid.UUID, file_name: str) -> Path:
    dest = staging_dir(job_id) / file_name
    await async_files.move(stitched, dest)
    return dest


async def cleanup_temp(upload_id: uuid.UUID) -> None:
    path = temp_dir(upload_id)
    if await async_files.path_exists(path):
        await async_files.rmtree(path)


async def validate_staged_file(staged_path: Path, file_name: str) -> str:
    return await asyncio.to_thread(validate_file_content, staged_path, file_name)
