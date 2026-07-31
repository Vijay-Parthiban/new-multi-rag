import re
import uuid
from pathlib import Path

from src.file_manager.core.errors import ValidationError
from src.shared.config.settings import get_settings


async def s3_download_to_temp(bucket: str, key: str) -> Path | None:
    """Download an S3 object to a local temp file for processing.

    Returns the local path, or None if the object doesn't exist.
    Caller must clean up the file after processing.
    """
    from src.shared.storage.s3_client import get_object, head_object

    if not await head_object(bucket, key):
        return None

    data = await get_object(bucket, key)
    temp_root = storage_root() / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    suffix = Path(key).suffix
    dest = temp_root / f"s3_dl_{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return dest

_DIR_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_UNSAFE_NAME = re.compile(r"[^\w.\- ]")


def sanitize_directory_name(name: str) -> str:
    cleaned = name.strip().lower()
    if not _DIR_PATTERN.match(cleaned):
        raise ValidationError(
            "INVALID_DIRECTORY_NAME",
            "Directory name must be 1-64 chars: lowercase letters, digits, hyphen, underscore.",
            {"name": name},
        )
    return cleaned


def sanitize_file_name(name: str) -> str:
    base = Path(name).name.strip()
    if not base or base in {".", ".."}:
        raise ValidationError("INVALID_FILE_NAME", "File name is invalid.", {"name": name})
    safe = _UNSAFE_NAME.sub("_", base)
    return safe[:512]


def storage_root() -> Path:
    """Local transient storage root for temp/staging (chunks).

    Permanent file storage uses MinIO (S3); this is only for ephemeral
    upload staging and chunk assembly.
    """
    root = Path(get_settings().storage_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_storage_layout() -> Path:
    """Create local transient subdirs at runtime.

    temp/ and staging/ are local-only for chunk assembly during upload.
    """
    root = storage_root()
    for name in ("temp", "staging"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def temp_dir(upload_id: uuid.UUID) -> Path:
    path = storage_root() / "temp" / str(upload_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def staging_dir(job_id: uuid.UUID) -> Path:
    path = storage_root() / "staging" / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def s3_stored_key(directory_name: str, original_name: str) -> str:
    """Generate the S3 object key for a stored file."""
    return f"uploads/{directory_name}/{unique_stored_name(original_name)}"


def unique_stored_name(original_name: str) -> str:
    safe = sanitize_file_name(original_name)
    return f"{uuid.uuid4().hex[:12]}-{safe}"
