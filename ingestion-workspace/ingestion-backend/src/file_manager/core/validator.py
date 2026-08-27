from pathlib import Path

import filetype

from src.file_manager.core.errors import ValidationError
from src.file_manager.utils.paths import sanitize_file_name

BLOCKED_MIME_PREFIXES = ("video/", "audio/")
BLOCKED_EXTENSIONS = {
    "mp4", "mov", "avi", "mkv", "webm", "wmv", "flv", "m4v",
    "mp3", "wav", "ogg", "aac", "flac", "m4a", "wma", "aiff",
}


def validate_file_name(file_name: str) -> str:
    """
    Sanitizes the incoming filename against trailing dot exploits or blocked extensions.
    Specifically guarantees no heavy video/audio container formats bypass the pipeline constraints.

    Args:
        file_name: The raw uploaded file string.

    Returns:
        The sanitized safe string.

    Raises:
        ValidationError: If the parsed suffix exists in the blocked list.
    """
    safe_name = sanitize_file_name(file_name)
    ext = Path(safe_name).suffix.lstrip(".").lower()
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError(
            "FILE_TYPE_BLOCKED",
            f"File type '.{ext}' is not allowed (video/audio blocked).",
            {"file_name": file_name},
        )
    return safe_name


def validate_file_content(path: Path, file_name: str) -> str:
    """
    Deep inspects a written file on disk by reading its magic bytes header using 'filetype' library.
    It asserts that the literal mime type does not belong to a blocked audio/video prefix,
    which prevents mislabelled files masking as PDF/text from causing pipeline chaos.

    Args:
        path: Pathlib object pointing to the locally synced tmp/upload storage path.
        file_name: Original file_name from the client to doubly check extensions.

    Returns:
        The detected true mime_type string.

    Raises:
        ValidationError: If type detection yields a forbidden media container.
    """
    validate_file_name(file_name)

    kind = filetype.guess(str(path))
    if kind is None:
        return "application/octet-stream"

    if kind.mime.startswith(BLOCKED_MIME_PREFIXES):
        raise ValidationError(
            "FILE_TYPE_BLOCKED",
            f"Detected media type '{kind.mime}' is not allowed.",
            {"file_name": file_name, "mime_type": kind.mime},
        )

    ext = Path(file_name).suffix.lstrip(".").lower()
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError(
            "FILE_TYPE_BLOCKED",
            f"File extension '.{ext}' is not allowed.",
            {"file_name": file_name},
        )

    return kind.mime
