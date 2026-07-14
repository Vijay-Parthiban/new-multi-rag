from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from rag_core import PipelineRequest, RerankResult
from rag_shared.types import RerankedChunk, RetrievedChunk

router = APIRouter(tags=["rerank"])


class RerankResponse(BaseModel):
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RerankedChunk]
    latency_ms: dict[str, int]


@router.post("/rerank", response_model=RerankResponse)
def rerank_chunks(request: Request, body: PipelineRequest) -> RerankResponse:
    pipeline = request.app.state.pipeline
    config, source_type, source_id = pipeline.from_request(body)
    result: RerankResult = pipeline.rerank(
        body.query,
        config=config,
        source_type=source_type,
        source_id=source_id,
    )
    return RerankResponse(
        retrieved_chunks=result.retrieved_chunks,
        reranked_chunks=result.reranked_chunks,
        latency_ms=result.latency_ms,
    )
