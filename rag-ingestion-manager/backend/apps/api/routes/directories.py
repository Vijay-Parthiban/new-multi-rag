from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.file_manager.core.storage import get_directory
from src.shared.db.models import Directory, FileRecord, FileStatus
from src.shared.db.session import get_db

router = APIRouter(prefix="/api/directories", tags=["directories"])


async def _file_to_dict(f: FileRecord, db: AsyncSession) -> dict:
    duplicate_of_name = None
    if f.duplicate_of_file_id:
        original = await db.get(FileRecord, f.duplicate_of_file_id)
        duplicate_of_name = original.original_name if original else None

    return {
        "id": str(f.id),
        "original_name": f.original_name,
        "mime_type": f.mime_type,
        "size_bytes": f.size_bytes,
        "content_hash": f.content_hash,
        "client_content_hash": f.client_content_hash,
        "hash_verified": f.hash_verified,
        "status": f.status.value,
        "error_message": f.error_message,
        "duplicate_of_file_id": str(f.duplicate_of_file_id) if f.duplicate_of_file_id else None,
        "duplicate_of_file_name": duplicate_of_name,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }


@router.get("", status_code=200)
async def list_directories(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(Directory).order_by(Directory.name))
    rows = result.scalars().all()
    return [{"name": d.name, "id": str(d.id), "created_at": d.created_at.isoformat()} for d in rows]


@router.get("/{name}/files", status_code=200)
async def list_files(name: str, db: Annotated[AsyncSession, Depends(get_db)]):
    directory = await get_directory(db, name)
    result = await db.execute(
        select(FileRecord)
        .where(
            FileRecord.directory_id == directory.id,
            FileRecord.status != FileStatus.DELETED,
        )
        .order_by(FileRecord.created_at.desc())
    )
    files = result.scalars().all()
    return [await _file_to_dict(f, db) for f in files]
