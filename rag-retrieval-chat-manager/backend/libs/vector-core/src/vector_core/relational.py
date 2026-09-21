"""pgvector reader and reciprocal rank fusion.

The ingestion fanout writes one row per chunk to a ``chunks`` table in a schema
named after the knowledge product. This reads it back with a nearest-neighbour
query, and fuses rankings when a strategy needs more than one store.
"""

from __future__ import annotations

import logging
import re

import psycopg
from rag_shared.config import Settings

from vector_core.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


class RelationalStoreUnavailable(RuntimeError):
    """The pgvector store the pipeline points at cannot be reached."""


_IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")
_DEFAULT_SCHEMA = "public"
_DEFAULT_TABLE = "chunks"
_FILE_INGEST = "file_ingest"

_COLUMNS = (
    "id",
    "file_key",
    "source_id",
    "page_index",
    "chunk_index",
    "modality",
    "record_type",
    "parent_ref",
    "content",
    "created_at",
)


def _safe_ident(name: str | None, fallback: str) -> str:
    """Guard an identifier that came from stored destination config."""
    if name and _IDENT_RE.match(name):
        return name
    return fallback


def _map_row(row: dict) -> dict[str, object]:
    file_key = row.get("file_key")
    return {
        "id": str(row.get("id")),
        "score": float(row.get("score") or 0.0),
        "type": str(row.get("modality") or "text"),
        "content": str(row.get("content") or ""),
        "source_type": _FILE_INGEST,
        "source_id": str(row.get("source_id") or ""),
        "source_locator": str(file_key or ""),
        "chunk_index": row.get("chunk_index"),
        "title": str(file_key) if file_key else None,
        "source_url": None,
        "scrape_job_id": None,
        "image_base64": None,
        "mime_type": None,
        "file_name": str(file_key) if file_key else None,
        "page_index": row.get("page_index"),
        "file_key": file_key,
    }


def search_pgvector_chunks(
    settings: Settings,
    *,
    query_text: str,
    schema: str | None,
    table: str | None,
    limit: int = 20,
    embedding_model: str | None = None,
) -> list[dict[str, object]]:
    """Return the nearest chunks by cosine distance, closest first.

    The embedding model must be the one the fanout used, or the distances are
    meaningless, so the caller passes the product's model.
    """
    safe_schema = _safe_ident(schema, _DEFAULT_SCHEMA)
    safe_table = _safe_ident(table, _DEFAULT_TABLE)
    model = embedding_model or settings.embedding_model
    embedder = EmbeddingClient(
        base_url=settings.litellm_base_url,
        api_key=settings.openai_api_key,
        model=model,
    )
    vector = embedder.embed_text(query_text)

    # The schema lives in the ingestion database, not this service's own.
    dsn = settings.ingestion_database_url
    columns = ", ".join(_COLUMNS)
    sql = (
        f'SELECT {columns}, 1 - (embedding <=> %s::vector) AS score '
        f'FROM "{safe_schema}"."{safe_table}" '
        f"WHERE embedding IS NOT NULL "
        f"ORDER BY embedding <=> %s::vector "
        f"LIMIT %s"
    )
    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(sql, (vector, vector, limit))
                rows = cur.fetchall()
    except psycopg.Error as exc:
        raise RelationalStoreUnavailable(
            f"PostgreSQL store {safe_schema}.{safe_table} is not readable: {exc}"
        ) from exc

    results = [_map_row(row) for row in rows]
    logger.info(
        "pgvector_search schema=%s table=%s model=%s limit=%s hits=%s",
        safe_schema,
        safe_table,
        model,
        limit,
        len(results),
    )
    return results


def _chunk_key(hit: dict[str, object]) -> tuple[str, str, object, object]:
    """The fanout writes the same file_key to every destination, so this
    identifies one chunk across Qdrant, OpenSearch and pgvector."""
    return (
        str(hit.get("source_id") or ""),
        str(hit.get("file_key") or hit.get("source_locator") or ""),
        hit.get("page_index"),
        hit.get("chunk_index"),
    )


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, object]]],
    *,
    k: int = 60,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Fuse rankings with reciprocal rank fusion.

    Each list contributes ``1 / (k + rank)`` per chunk. A chunk that ranks well
    in both lists outranks one that ranks well in only one, which is the point:
    the two stores measure different kinds of relevance. ``k = 60`` is the value
    the RRF paper and OpenSearch's own implementation use.
    """
    scores: dict[tuple, float] = {}
    best: dict[tuple, float] = {}
    hits: dict[tuple, dict[str, object]] = {}

    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            key = _chunk_key(hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            single = float(hit.get("score") or 0.0)
            if key not in hits or single > best.get(key, float("-inf")):
                best[key] = single
                hits[key] = hit

    fused: list[dict[str, object]] = []
    for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        hit = dict(hits[key])
        hit["score"] = score
        fused.append(hit)
    return fused[:limit]
