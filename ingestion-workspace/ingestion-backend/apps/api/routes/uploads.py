import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.file_manager.core import chunks, service
from src.shared.db.models import JobOperation
from src.shared.db.session import get_db

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class InitUploadRequest(BaseModel):
    directory_name: str = Field(min_length=1, max_length=64)
    file_name: str = Field(min_length=1, max_length=512)
    total_chunks: int = Field(ge=1)
    total_size: int = Field(ge=1)
    mime_type: str | None = None
    client_content_hash: str = Field(min_length=64, max_length=64)


@router.post("/init", status_code=201)
async def init_upload(body: InitUploadRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    upload = await chunks.init_chunk_upload(
        db,
        directory_name=body.directory_name,
        file_name=body.file_name,
        total_chunks=body.total_chunks,
        total_size=body.total_size,
        mime_type=body.mime_type,
        client_content_hash=body.client_content_hash,
        operation=JobOperation.UPLOAD,
    )
    return {
        "upload_id": str(upload.id),
        "directory_name": upload.directory_name,
        "file_name": upload.file_name,
    }


@router.put("/{upload_id}/chunks/{chunk_index}", status_code=204)
async def upload_chunk(
    upload_id: uuid.UUID,
    chunk_index: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    chunk: UploadFile = File(...),
):
    data = await chunk.read()
    if not data:
        from src.file_manager.core.errors import ValidationError

        raise ValidationError("EMPTY_CHUNK", "Chunk body must not be empty.")
    await chunks.save_chunk(upload_id, chunk_index, data, db)


@router.post("/{upload_id}/complete", status_code=202)
async def complete_upload(upload_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.complete_chunk_upload(db, upload_id)
