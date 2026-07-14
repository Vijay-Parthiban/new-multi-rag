import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from crawler_shared.config import Settings, get_settings
from crawler_shared.types import SourceTypeFilter
from web_scrapper.vector.search import search_scrape_chunks

logger = logging.getLogger(__name__)
router = APIRouter()

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
        return [SearchResultResponse(**hit) for hit in hits]  # type: ignore[arg-type]
    except Exception as exc:
        logger.error("search_endpoint_failed error=%s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search retrieval failure: {str(exc)}") from exc
