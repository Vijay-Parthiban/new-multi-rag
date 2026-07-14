from __future__ import annotations

import os
from pathlib import PurePath
from urllib.parse import urlparse

from rag_shared.types import RetrievedChunk


def normalize_source(value: str) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.netloc.replace("www.", "") + parsed.path.rstrip("/")
    else:
        text = os.path.basename(text)
    return text


def is_relevant_chunk(chunk: RetrievedChunk, expected: set[str]) -> bool:
    candidates = {
        chunk.source_locator,
        chunk.title or "",
        str(chunk.metadata.get("file_name", "")),
        str(chunk.metadata.get("url", "")),
    }
    normalized_expected = {normalize_source(e) for e in expected if e}
    for candidate in candidates:
        norm_c = normalize_source(candidate)
        if not norm_c:
            continue
        for exp in normalized_expected:
            if norm_c in exp or exp in norm_c:
                return True
    return False
