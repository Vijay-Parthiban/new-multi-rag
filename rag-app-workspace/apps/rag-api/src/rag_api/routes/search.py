from __future__ import annotations

import logging
import base64
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rag_shared.config import Settings, get_settings
from rag_shared.types import SourceTypeFilter
from vector_core import search_scrape_chunks
from vector_core.vision_client import VisionClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

SearchMode = Literal["hybrid", "dense", "sparse"]


class SearchResultResponse(BaseModel):
    id: str
    score: float
    type: str
    content: str
    source_type: str
    source_id: str
    source_locator: str
    chunk_index: int | None = None
    source_url: str
    title: str | None = None
    scrape_job_id: str


class RAGQueryRequest(BaseModel):
    text_query: str = Field(..., description="The semantic search question text.")
    limit: int = Field(default=5, ge=1, le=50, description="Number of items to retrieve.")
    mode: SearchMode = Field(
        default="hybrid",
        description="Search strategy: hybrid (dense+sparse RRF), dense semantic only, or sparse keyword only.",
    )
    source_type: SourceTypeFilter = Field(
        default="all",
        description="Filter by ingest source: all, web_scrape, or file_ingest.",
    )
    source_id: str | None = Field(
        default=None,
        description="Optional job/document id to scope retrieval (scrape_job_id or ingest_job_id).",
    )


class RAGChunkItem(BaseModel):
    id: str
    score: float
    type: str = Field(..., description="Modality variant: 'text' or 'image'")
    content: str = Field(..., description="Raw string segment or base64 data URI string.")
    source_type: str
    source_id: str
    source_locator: str
    chunk_index: int | None = None
    source_url: str
    title: str | None = None
    scrape_job_id: str


def _to_chunk_items(hits: list[dict[str, object]]) -> list[RAGChunkItem]:
    return [
        RAGChunkItem(
            id=str(hit["id"]),
            score=float(hit["score"]),  # type: ignore[arg-type]
            type=str(hit["type"]),
            content=str(hit["content"]),
            source_type=str(hit["source_type"]),
            source_id=str(hit["source_id"]),
            source_locator=str(hit["source_locator"]),
            chunk_index=int(hit["chunk_index"]) if hit.get("chunk_index") is not None else None,
            source_url=str(hit["source_url"]),
            title=hit["title"] if hit.get("title") is None else str(hit["title"]),
            scrape_job_id=str(hit["scrape_job_id"]),
        )
        for hit in hits
    ]


@router.get("/search", response_model=list[SearchResultResponse])
async def search_points(
    query_text: str,
    limit: int = 5,
    mode: SearchMode = "hybrid",
    source_type: SourceTypeFilter = "all",
    source_id: str | None = None,
    settings: Settings = Depends(get_settings),
) -> list[SearchResultResponse]:
    try:
        hits = search_scrape_chunks(
            settings,
            query_text=query_text,
            limit=limit,
            mode=mode,
            source_type=source_type,
            source_id=source_id,
        )
        # Separate image and text hits
        image_hits = [h for h in hits if h.get("type") == "image"]
        text_hits = [h for h in hits if h.get("type") != "image"]

        # Process image hits with VisionClient
        image_responses: list[str] = []
        if image_hits:
            vision = VisionClient(base_url=settings.litellm_base_url, api_key=settings.openai_api_key)
            for img_hit in image_hits:
                # Assume payload contains base64 image data under 'content'
                img_data = img_hit.get("content", "")
                if img_data.startswith("data:image"):
                    # extract base64 part
                    b64 = img_data.split(",", 1)[-1]
                    image_bytes = base64.b64decode(b64)
                else:
                    # if raw bytes path stored elsewhere, skip
                    continue
                resp = vision.generate(image_bytes)
                image_responses.append(resp)

        # Generate text response using provider model (same as before)
        text_response = None
        if text_hits:
            # reuse existing SearchResultResponse conversion for consistency
            text_response = [SearchResultResponse(**hit) for hit in text_hits]

        # Combine responses
        if image_responses and text_response:
            # Synthesize final answer via provider LLM (placeholder)
            # Here we just concatenate for simplicity
            combined = "\n---\n".join([str(r) for r in text_response] + image_responses)
            return combined
        elif image_responses:
            return image_responses
        else:
            return [SearchResultResponse(**hit) for hit in hits]  # type: ignore[arg-type]
    except Exception as exc:
        logger.error("search_endpoint_failed error=%s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search retrieval failure: {str(exc)}") from exc


@router.post("/scrapes/query", response_model=list[RAGChunkItem])
def query_vector_chunks(
    payload: RAGQueryRequest,
    settings: Settings = Depends(get_settings),
) -> list[RAGChunkItem]:
    """Search stored chunks with dense, sparse, or hybrid retrieval."""
    try:
        hits = search_scrape_chunks(
            settings,
            query_text=payload.text_query,
            limit=payload.limit,
            mode=payload.mode,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
        return _to_chunk_items(hits)
    except Exception as exc:
        logger.error("vector_search_endpoint_failed error=%s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector retrieval failure: {str(exc)}") from exc
