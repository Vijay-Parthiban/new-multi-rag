from __future__ import annotations

from rag_shared.types import RetrievedChunk


def chunk_from_search_hit(hit: dict[str, object]) -> RetrievedChunk:
    chunk_index = hit.get("chunk_index")
    return RetrievedChunk(
        id=str(hit["id"]),
        content=str(hit["content"]),
        source_type=str(hit["source_type"]),
        source_id=str(hit["source_id"]),
        source_locator=str(hit["source_locator"]),
        chunk_index=int(chunk_index) if chunk_index is not None else 0,
        chunk_type=str(hit["type"]),
        title=str(hit["title"]) if hit.get("title") is not None else None,
        retrieval_score=float(hit["score"]),
        metadata={
            "source_url": hit.get("source_url"),
            "scrape_job_id": hit.get("scrape_job_id"),
            "image_base64": hit.get("image_base64"),
            "mime_type": hit.get("mime_type"),
        },
    )
