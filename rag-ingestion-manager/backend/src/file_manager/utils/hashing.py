import hashlib
import re
from pathlib import Path

from src.file_manager.core.errors import ValidationError

_CHUNK = 1024 * 1024  # 1 MB
_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def normalize_hash(value: str) -> str:
    cleaned = value.strip().lower()
    if not _HASH_PATTERN.match(cleaned):
        raise ValidationError(
            "INVALID_CONTENT_HASH",
            "content_hash must be a 64-character SHA-256 hex string.",
            {"content_hash": value},
        )
    return cleaned


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def verify_stitched_hash(stitched: Path, client_content_hash: str) -> str:
    """Compute server hash and verify it matches the client hash."""
    client_hash = normalize_hash(client_content_hash)
    server_hash = compute_file_hash(stitched)
    if server_hash != client_hash:
        raise ValidationError(
            "CORRUPTION_DETECTED",
            "Uploaded file hash does not match — file may be corrupted.",
            {
                "client_content_hash": client_hash,
                "server_content_hash": server_hash,
            },
        )
    return server_hash
