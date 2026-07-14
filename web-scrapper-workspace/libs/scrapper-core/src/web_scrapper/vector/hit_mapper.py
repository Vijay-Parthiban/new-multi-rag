from qdrant_client.http import models as qmodels

from crawler_shared.types import WEB_SCRAPE_SOURCE_TYPE


def resolve_content(payload: dict[str, object]) -> str:
    return str(
        payload.get("content")
        or payload.get("text")
        or payload.get("markdown")
        or ""
    )


def map_scored_point(hit: qmodels.ScoredPoint) -> dict[str, object]:
    """Map a Qdrant hit to a source-agnostic retrieval result dict."""
    payload = hit.payload or {}
    source_type = str(payload.get("source_type") or WEB_SCRAPE_SOURCE_TYPE)
    source_id = str(payload.get("source_id") or payload.get("scrape_job_id") or "")
    source_locator = str(payload.get("source_locator") or payload.get("url") or "")
    chunk_index = payload.get("chunk_index")
    title = payload.get("title")

    return {
        "id": str(hit.id),
        "score": float(hit.score),
        "type": str(payload.get("type", "text")),
        "content": resolve_content(payload),
        "source_type": source_type,
        "source_id": source_id,
        "source_locator": source_locator,
        "chunk_index": int(chunk_index) if chunk_index is not None else None,
        "title": str(title) if title is not None else None,
        "source_url": source_locator,
        "scrape_job_id": str(payload.get("scrape_job_id") or source_id),
    }
