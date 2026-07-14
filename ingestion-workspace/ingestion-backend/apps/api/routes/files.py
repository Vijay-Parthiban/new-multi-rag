import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core import chunks, service
from src.file_manager.core.errors import NotFoundError
from src.file_manager.core.storage import request_delete, request_rename
from src.file_manager.utils.paths import storage_root
from src.shared.db.models import FileRecord, FileStatus, JobOperation
from src.shared.db.session import get_db
from src.shared.io import async_files

router = APIRouter(prefix="/api/files", tags=["files"])


class RenameRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=512)


class InitAppendRequest(BaseModel):
    total_chunks: int = Field(ge=1)
    total_size: int = Field(ge=1)
    mime_type: str | None = None
    client_content_hash: str = Field(min_length=64, max_length=64)


async def _file_response(file_record: FileRecord, db: AsyncSession) -> dict:
    duplicate_of_name = None
    if file_record.duplicate_of_file_id:
        original = await db.get(FileRecord, file_record.duplicate_of_file_id)
        duplicate_of_name = original.original_name if original else None

    return {
        "id": str(file_record.id),
        "directory_name": file_record.directory.name,
        "original_name": file_record.original_name,
        "mime_type": file_record.mime_type,
        "size_bytes": file_record.size_bytes,
        "content_hash": file_record.content_hash,
        "client_content_hash": file_record.client_content_hash,
        "hash_verified": file_record.hash_verified,
        "status": file_record.status.value,
        "error_message": file_record.error_message,
        "duplicate_of_file_id": (
            str(file_record.duplicate_of_file_id) if file_record.duplicate_of_file_id else None
        ),
        "duplicate_of_file_name": duplicate_of_name,
        "created_at": file_record.created_at.isoformat(),
        "updated_at": file_record.updated_at.isoformat(),
    }


@router.get("/{file_id}", status_code=200)
async def get_file(file_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    file_record = await db.get(
        FileRecord, file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record or file_record.status == FileStatus.DELETED:
        raise NotFoundError("FILE_NOT_FOUND", "File not found.")
    return await _file_response(file_record, db)


@router.get("/{file_id}/view")
async def view_file(file_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    file_record = await db.get(FileRecord, file_id)
    if not file_record or file_record.status != FileStatus.SYNCED or not file_record.relative_path:
        raise NotFoundError("FILE_NOT_AVAILABLE", "File is not available for viewing.")

    path = storage_root() / file_record.relative_path
    if not await async_files.path_exists(path):
        raise NotFoundError("FILE_MISSING", "File not found on storage.")

    return FileResponse(
        path=path,
        media_type=file_record.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{file_record.original_name}"'},
    )


@router.patch("/{file_id}", status_code=202)
async def rename_file(
    file_id: uuid.UUID, body: RenameRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    job = await request_rename(db, file_id, body.new_name)
    return {"job_id": str(job.id), "status": "processing"}


@router.delete("/{file_id}", status_code=202)
async def delete_file(file_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    job = await request_delete(db, file_id)
    return {"job_id": str(job.id), "status": "processing"}


@router.post("/{file_id}/append/init", status_code=201)
async def init_append(
    file_id: uuid.UUID, body: InitAppendRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    file_record = await db.get(
        FileRecord, file_id, options=(selectinload(FileRecord.directory),)
    )
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File not found.")
    if file_record.status != FileStatus.SYNCED:
        from src.file_manager.core.errors import ConflictError

        raise ConflictError("FILE_NOT_SYNCED", "File must be synced before appending.")

    upload = await chunks.init_chunk_upload(
        db,
        directory_name=file_record.directory.name,
        file_name=file_record.original_name,
        total_chunks=body.total_chunks,
        total_size=body.total_size,
        mime_type=body.mime_type,
        client_content_hash=body.client_content_hash,
        target_file_id=file_id,
        operation=JobOperation.APPEND,
    )
    return {"upload_id": str(upload.id), "file_id": str(file_id)}


@router.post("/{file_id}/append/{upload_id}/complete", status_code=202)
async def complete_append(
    file_id: uuid.UUID, upload_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    file_record = await db.get(FileRecord, file_id)
    if not file_record:
        raise NotFoundError("FILE_NOT_FOUND", "File not found.")
    return await service.complete_chunk_upload(db, upload_id)
