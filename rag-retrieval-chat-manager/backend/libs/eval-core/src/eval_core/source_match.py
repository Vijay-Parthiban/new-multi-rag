from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from rag_shared.types import RetrievedChunk

logger = logging.getLogger(__name__)


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


_PAGE_SUFFIX = re.compile(r"^(?P<name>.+?)_p(?P<page>\d+)$")


def parse_expected_sources(raw: list[Any] | None) -> list[ExpectedSource]:
    """Normalize golden-dataset sources into name + optional page objects.

    A CSV cannot carry a page: `source_doc_id` maps to plain strings, so `{name, page}`
    objects — which the JSON form supports — were unreachable from an uploaded CSV. A
    string ending in `_p<digits>` therefore splits into a name and a page:

        TCS-Global-Whistle-Blower-Policy.pdf_p3  ->  {name: "...pdf", page: 3}

    Keep this in step with `_chunk_page`, which reads `metadata.page_index` and adds one.
    """
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
            if not name:
                continue
            match = _PAGE_SUFFIX.match(name)
            if match:
                out.append(ExpectedSource(name=match.group("name"), page=int(match.group("page"))))
            else:
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


def matches_expected_source(chunk: RetrievedChunk, expected: ExpectedSource) -> bool:
    """True when chunk source locator/name matches and page matches when required."""
    candidates = _chunk_source_candidates(chunk)
    chunk_page = _chunk_page(chunk)

    name_match = any(_name_matches(c, expected.name) for c in candidates)
    if not name_match:
        # Worth one debug line, not one per chunk per source: an all-zero retrieval block
        # means no expected name matched anything, and this is the line that shows why.
        logger.debug(
            "no source match: expected name=%r page=%r, candidates=%r",
            expected.name,
            expected.page,
            candidates,
        )
        return False
    if expected.page is None:
        return True

    return chunk_page is not None and chunk_page == expected.page


def is_relevant_chunk(
    chunk: RetrievedChunk,
    expected: set[str] | list[str] | list[ExpectedSource] | list[Any],
) -> bool:
    sources = parse_expected_sources(list(expected) if not isinstance(expected, list) else expected)
    if not sources and isinstance(expected, set):
        sources = parse_expected_sources(list(expected))
    return any(matches_expected_source(chunk, src) for src in sources)
