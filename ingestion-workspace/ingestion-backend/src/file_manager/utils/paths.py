import re
import uuid
from pathlib import Path

from src.file_manager.core.errors import ValidationError
from src.shared.config.settings import get_settings

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
    root = Path(get_settings().storage_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_storage_layout() -> Path:
    """Create storage subdirs at runtime (not in the Docker image).

    Pre-creating these in the Dockerfile conflicts with named-volume init
    when api and worker mount the same volume concurrently.
    """
    root = storage_root()
    for name in ("temp", "staging", "uploads"):
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


def uploads_dir(directory_name: str) -> Path:
    path = storage_root() / "uploads" / directory_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_stored_name(original_name: str) -> str:
    safe = sanitize_file_name(original_name)
    return f"{uuid.uuid4().hex[:12]}-{safe}"
