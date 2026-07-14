from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rag_shared.config import Settings, get_settings
from rag_shared.types import SourceTypeFilter
from vector_core import search_scrape_chunks

from rag_api.routes.search import RAGChunkItem, _to_chunk_items

logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieve"])

SearchMode = Literal["hybrid", "dense", "sparse"]


class RetrieveRequest(BaseModel):
    """Legacy alias — prefer POST /scrapes/query with RAGQueryRequest."""

    text_query: str | None = Field(default=None, description="The semantic search question text.")
    limit: int = Field(default=5, ge=1, le=50, description="Number of items to retrieve.")
    mode: SearchMode = Field(default="hybrid")
    source_type: SourceTypeFilter = Field(default="all")
    source_id: str | None = None

    # Deprecated field names kept for backward compatibility
    query: str | None = Field(default=None, deprecated=True)
    retrieval_mode: SearchMode | None = Field(default=None, deprecated=True)
    retrieve_limit: int | None = Field(default=None, ge=1, le=50, deprecated=True)


@router.post("/retrieve", response_model=list[RAGChunkItem], deprecated=True)
def retrieve_chunks(
    body: RetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> list[RAGChunkItem]:
    """Legacy retrieve endpoint — same response shape as POST /scrapes/query."""
    text_query = body.text_query or body.query or ""
    if not text_query.strip():
        raise HTTPException(status_code=422, detail="text_query is required")

    mode = body.mode if body.retrieval_mode is None else body.retrieval_mode
    limit = body.limit if body.retrieve_limit is None else body.retrieve_limit

    try:
        hits = search_scrape_chunks(
            settings,
            query_text=text_query,
            limit=limit,
            mode=mode,
            source_type=body.source_type,
            source_id=body.source_id,
        )
        return _to_chunk_items(hits)
    except Exception as exc:
        logger.error("retrieve_endpoint_failed error=%s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector retrieval failure: {str(exc)}") from exc
