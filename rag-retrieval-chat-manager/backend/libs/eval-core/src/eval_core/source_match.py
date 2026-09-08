from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from rag_shared.types import RetrievedChunk


@dataclass(frozen=True)
class ExpectedSource:
    name: str
    page: int | None = None


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


def parse_expected_sources(raw: list[Any] | None) -> list[ExpectedSource]:
    """Normalize golden-dataset sources into name + optional page objects."""
    if not raw:
        return []
    out: list[ExpectedSource] = []
    for entry in raw:
        if isinstance(entry, ExpectedSource):
            if entry.name.strip():
                out.append(entry)
            continue
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                out.append(ExpectedSource(name=name))
            continue
        if isinstance(entry, dict):
            name = str(entry.get("name") or entry.get("source") or "").strip()
            if not name:
                continue
            page = entry.get("page")
            page_int: int | None = None
            if page is not None and page != "":
                try:
                    page_int = int(page)
                except (TypeError, ValueError):
                    page_int = None
            out.append(ExpectedSource(name=name, page=page_int))
    return out


def _chunk_page(chunk: RetrievedChunk) -> int | None:
    meta = chunk.metadata or {}
    for key in ("page_index", "page_number", "page", "page_num", "page_label"):
        value = meta.get(key)
        if value is None or value == "":
            continue
        try:
            val = int(value)
            if key == "page_index":
                return val + 1
            return val
        except (TypeError, ValueError):
            continue
    return None


def _chunk_source_candidates(chunk: RetrievedChunk) -> list[str]:
    meta = chunk.metadata or {}
    return [
        chunk.source_locator,
        chunk.title or "",
        str(meta.get("file_name", "")),
        str(meta.get("url", "")),
        str(meta.get("source_locator", "")),
    ]


def _name_matches(candidate: str, expected_name: str) -> bool:
    norm_c = normalize_source(candidate)
    norm_e = normalize_source(expected_name)
    if not norm_c or not norm_e:
        return False
    return norm_c in norm_e or norm_e in norm_c


import logging

logger = logging.getLogger(__name__)

def matches_expected_source(chunk: RetrievedChunk, expected: ExpectedSource) -> bool:
    """True when chunk source locator/name matches and page matches when required."""
    candidates = _chunk_source_candidates(chunk)
    chunk_page = _chunk_page(chunk)
    
    name_match = False
    matched_c = None
    for c in candidates:
        if _name_matches(c, expected.name):
            name_match = True
            matched_c = c
            break
            
    print(f"[SOURCE_MATCH DEBUG] Expected: file='{expected.name}', page={expected.page}", flush=True)
    print(f"  -> Chunk Candidates: {candidates}", flush=True)
    print(f"  -> Chunk Page Found: {chunk_page}", flush=True)
    print(f"  -> Name Match Result: {name_match} {f'(on {matched_c})' if name_match else ''}", flush=True)

    if not name_match:
        return False
    if expected.page is None:
        return True
    
    page_match = (chunk_page is not None and chunk_page == expected.page)
    print(f"  -> Page Match Result: {page_match}", flush=True)
    return page_match


def is_relevant_chunk(
    chunk: RetrievedChunk,
    expected: set[str] | list[str] | list[ExpectedSource] | list[Any],
) -> bool:
    sources = parse_expected_sources(list(expected) if not isinstance(expected, list) else expected)
    if not sources and isinstance(expected, set):
        sources = parse_expected_sources(list(expected))
    return any(matches_expected_source(chunk, src) for src in sources)
