from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from rag_core import PipelineRequest

router = APIRouter(tags=["generate"])


class SourceCitation(BaseModel):
    source_locator: str
    chunk_index: int
    rerank_score: float


class GenerateResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]
    latency_ms: dict[str, int]


@router.post("/generate", response_model=GenerateResponse)
def generate_answer(request: Request, body: PipelineRequest) -> GenerateResponse:
    pipeline = request.app.state.pipeline
    config, source_type, source_id = pipeline.from_request(body)
    result = pipeline.generate(
        body.query,
        config=config,
        source_type=source_type,
        source_id=source_id,
    )
    sources = [
        SourceCitation(
            source_locator=c.source_locator,
            chunk_index=c.chunk_index,
            rerank_score=c.rerank_score,
        )
        for c in result.reranked_chunks
    ]
    return GenerateResponse(
        answer=result.answer,
        sources=sources,
        latency_ms=result.latency_ms,
    )
