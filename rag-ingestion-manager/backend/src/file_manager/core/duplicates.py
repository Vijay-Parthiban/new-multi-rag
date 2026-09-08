import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.db.models import Directory, FileRecord, FileStatus


async def find_duplicate_in_directory(
    db: AsyncSession,
    directory_id: uuid.UUID,
    content_hash: str,
    *,
    exclude_file_id: uuid.UUID | None = None,
) -> FileRecord | None:
    query = select(FileRecord).where(
        FileRecord.directory_id == directory_id,
        FileRecord.content_hash == content_hash,
        FileRecord.status.in_([FileStatus.PROCESSING, FileStatus.SYNCED]),
    )
    if exclude_file_id:
        query = query.where(FileRecord.id != exclude_file_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_duplicate_record(
    db: AsyncSession,
    *,
    directory: Directory,
    original_name: str,
    mime_type: str,
    size_bytes: int,
    content_hash: str,
    client_content_hash: str | None,
    existing: FileRecord,
) -> FileRecord:
    file_record = FileRecord(
        directory_id=directory.id,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        client_content_hash=client_content_hash,
        hash_verified=True,
        status=FileStatus.DUPLICATE,
        duplicate_of_file_id=existing.id,
        error_message=f"Duplicate of {existing.original_name}",
    )
    db.add(file_record)
    await db.flush()
    return file_record


async def assert_no_duplicate_in_directory(
    db: AsyncSession,
    directory_id: uuid.UUID,
    content_hash: str,
    *,
    exclude_file_id: uuid.UUID | None = None,
) -> None:
    from src.file_manager.core.errors import ConflictError

    existing = await find_duplicate_in_directory(
        db, directory_id, content_hash, exclude_file_id=exclude_file_id
    )
    if not existing:
        return

    raise ConflictError(
        "DUPLICATE_FILE",
        "Append would make this file identical to another file in the directory.",
        {
            "content_hash": content_hash,
            "existing_file_id": str(existing.id),
            "existing_file_name": existing.original_name,
        },
    )
