"""Sanitize values before writing to Postgres text/JSONB columns."""
from __future__ import annotations

from typing import Any


def strip_null_bytes(value: Any) -> Any:
    """Remove \\x00 from strings recursively.

    Postgres rejects null bytes in text and JSON/JSONB (\\u0000).
    Chunk content from PDFs/OCR often contains them.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: strip_null_bytes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_null_bytes(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_null_bytes(v) for v in value)
    return value
