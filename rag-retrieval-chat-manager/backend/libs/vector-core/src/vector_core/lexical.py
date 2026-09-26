"""OpenSearch BM25 reader for a knowledge product's lexical index.

The ingestion fanout writes one document per chunk to the index named in the
product's ``lexical_opensearch`` destination. This reads it back. There is no
dedicated OpenSearch client in this backend: the fanout calls ``httpx``
directly, so this does the same rather than adding a dependency.
"""

from __future__ import annotations

import logging

import httpx
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0
# The index has no explicit mappings, so content and text are dynamic-mapped
# text fields. Both are searched: the fanout writes the same value to each.
_SEARCH_FIELDS = ["content", "text"]
_FILE_INGEST = "file_ingest"


def _auth(settings: Settings) -> tuple[str, str] | None:
    if settings.opensearch_username:
        return (settings.opensearch_username, settings.opensearch_password)
    return None


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _map_hit(hit: dict, index_name: str) -> dict[str, object]:
    source = hit.get("_source") or {}
    file_key = source.get("file_key")
    content = source.get("content") or source.get("text") or ""
    source_locator = source.get("source_locator") or file_key
    return {
        "id": str(hit.get("_id") or ""),
        "score": float(hit.get("_score") or 0.0),
        "type": str(source.get("type") or source.get("modality") or "text"),
        "content": str(content),
        "source_type": str(source.get("source_type") or _FILE_INGEST),
        "source_id": str(source.get("source_id") or ""),
        "source_locator": str(source_locator or ""),
        "chunk_index": _as_int(source.get("chunk_index")),
        "title": str(source.get("title") or file_key) if (source.get("title") or file_key) else None,
        "source_url": None,
        "scrape_job_id": None,
        "image_base64": None,
        "mime_type": None,
        "file_name": str(source.get("file_name") or file_key) if (source.get("file_name") or file_key) else None,
        "page_index": _as_int(source.get("page_index")),
        "file_key": file_key,
        "index_name": index_name,
    }


def search_lexical_index(
    settings: Settings,
    *,
    query_text: str,
    index_name: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return the BM25 hits for ``query_text``, best first.

    A missing index is not an error: a product that never synced has an empty
    index, and that answer is the same as no hits.
    """
    url = f"{settings.opensearch_url.rstrip('/')}/{index_name}/_search"
    body = {
        "size": limit,
        "query": {"multi_match": {"query": query_text, "fields": _SEARCH_FIELDS}},
    }
    try:
        response = httpx.post(url, json=body, auth=_auth(settings), timeout=_TIMEOUT_S)
    except httpx.TimeoutException:
        # The first query against a cold index can exceed the timeout while the
        # shard warms up. No hits is the honest answer, and it degrades to the
        # other retrieval paths instead of failing the whole chat request.
        logger.warning("lexical_search_timeout index=%s limit=%s", index_name, limit)
        return []
    if response.status_code == 404:
        logger.info("lexical_index_missing index=%s", index_name)
        return []
    response.raise_for_status()
    hits = ((response.json().get("hits") or {}).get("hits")) or []
    results = [_map_hit(hit, index_name) for hit in hits]
    logger.info("lexical_search index=%s limit=%s hits=%s", index_name, limit, len(results))
    return results
