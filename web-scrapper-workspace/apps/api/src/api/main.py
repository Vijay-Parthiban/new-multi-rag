import logging
from collections.abc import Generator
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.scrape_job import ScrapeJob
from crawler_db.services.crawl_service import CrawlService, ScrapeService
from crawler_db.session import get_session_factory
from crawler_shared.logging_config import setup_logging
from crawler_shared.config import get_settings  # Added to fetch system configs
from crawler_shared.types import SourceTypeFilter
from crawler_shared.redis.queue import enqueue_crawl, enqueue_crawl_and_scrape, enqueue_scrape

from web_scrapper.vector.search import search_scrape_chunks

from api.router import router

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Web Crawler API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
crawl_service = CrawlService()
scrape_service = ScrapeService()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency providing a DB session with commit/rollback handling."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("db_session_rollback")
        raise
    finally:
        session.close()


class CrawlCreateRequest(BaseModel):
    seed_url: str
    max_depth: int = Field(default=2, ge=0)
    max_pages: int = Field(default=50, ge=1)
    mode: Literal["httpx", "playwright", "auto"] = "httpx"


class CrawlResultResponse(BaseModel):
    links_file_path: str
    total_links: int
    pages_crawled: int
    metadata: dict | None = None


class CrawlJobResponse(BaseModel):
    id: UUID
    seed_url: str
    max_depth: int
    max_pages: int
    mode: str
    status: str
    error_message: str | None
    markdown_ingested: bool = False
    image_ingested: bool = False
    markdown_indexed_at: datetime | None = None
    image_indexed_at: datetime | None = None
    result: CrawlResultResponse | None = None

    @classmethod
    def from_model(cls, job: CrawlJob) -> "CrawlJobResponse":
        result = None
        if job.result is not None:
            result = CrawlResultResponse(
                links_file_path=job.result.links_file_path,
                total_links=job.result.total_links,
                pages_crawled=job.result.pages_crawled,
                metadata=job.result.metadata_,
            )
        return cls(
            id=job.id,
            seed_url=job.seed_url,
            max_depth=job.max_depth,
            max_pages=job.max_pages,
            mode=job.crawl_mode,
            status=job.status.value,
            error_message=job.error_message,
            markdown_ingested=job.markdown_ingested,
            image_ingested=job.image_ingested,
            markdown_indexed_at=job.markdown_indexed_at,
            image_indexed_at=job.image_indexed_at,
            result=result,
        )


class ScrapeCreateRequest(BaseModel):
    crawl_job_id: UUID
    embedding_source: Literal["markdown", "image"] = Field(
        default="markdown",
        description="Embed markdown text or screenshot image (base64 stored in job folder when image).",
    )


class ScrapeJobResponse(BaseModel):
    id: UUID
    crawl_job_id: UUID
    status: str
    output_dir: str | None
    embedding_source: str
    pages_scraped: int
    error_message: str | None

    @classmethod
    def from_model(cls, job: ScrapeJob) -> "ScrapeJobResponse":
        return cls(
            id=job.id,
            crawl_job_id=job.crawl_job_id,
            status=job.status.value,
            output_dir=job.output_dir,
            embedding_source=job.embedding_source,
            pages_scraped=job.pages_scraped,
            error_message=job.error_message,
        )


class CrawlScrapePipelineRequest(BaseModel):
    seed_url: str
    max_depth: int = Field(default=2, ge=0)
    max_pages: int = Field(default=50, ge=1)
    mode: Literal["httpx", "playwright", "auto"] = "httpx"
    embedding_source: Literal["markdown", "image"] = Field(
        default="markdown",
        description="Embed markdown text or screenshot image after crawl completes.",
    )
    qdrant_collection: str | None = Field(
        default=None,
        description="Target Qdrant collection for this pipeline run (required for ingestion pipelines).",
    )
    embedding_model: str | None = Field(
        default=None,
        description="LiteLLM embedding model for this pipeline run.",
    )
    sparse_embedding_model: str | None = Field(
        default=None,
        description="Sparse embedding model when use_sparse is true.",
    )
    pipeline_description: str | None = Field(
        default=None,
        description="Human-readable pipeline identifier for chat UI selection.",
    )
    use_sparse: bool = Field(
        default=True,
        description="When false, only dense vectors are upserted (naive RAG).",
    )


def _vector_config_from_payload(payload: CrawlScrapePipelineRequest) -> dict:
    return {
        "qdrant_collection": payload.qdrant_collection,
        "embedding_model": payload.embedding_model,
        "sparse_embedding_model": payload.sparse_embedding_model,
        "pipeline_description": payload.pipeline_description,
        "use_sparse": payload.use_sparse,
    }


class CrawlScrapePipelineResponse(BaseModel):
    crawl_job: CrawlJobResponse
    scrape_job: ScrapeJobResponse | None = None
    skipped: bool = False
    skip_reason: str | None = None


class LinkRecord(BaseModel):
    """One record from the `links.jsonl` crawl output file."""
    url: str
    depth: int
    parent: str | None = None
    status_code: int | None = None


# --- NEW SCHEMAS FOR MULTIMODAL RETRIEVAL ---

class RAGQueryRequest(BaseModel):
    text_query: str = Field(..., description="The semantic search question text.")
    limit: int = Field(default=5, ge=1, le=50, description="Number of items to retrieve.")
    mode: Literal["hybrid", "dense", "sparse"] = Field(
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/crawls", response_model=CrawlJobResponse, status_code=201)
def create_crawl(payload: CrawlCreateRequest, db: Session = Depends(get_db)) -> CrawlJobResponse:
    """Create a crawl job, enqueue it for the worker, and return the created job."""
    job = crawl_service.create_crawl_job(
        db,
        seed_url=payload.seed_url,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        crawl_mode=payload.mode,
    )
    db.commit()
    logger.info(
        "crawl_job_created id=%s seed_url=%s max_depth=%d max_pages=%d mode=%s",
        job.id,
        job.seed_url,
        job.max_depth,
        job.max_pages,
        job.crawl_mode,
    )
    enqueue_crawl(job.id)
    job = crawl_service.get_job(db, job.id)
    assert job is not None
    return CrawlJobResponse.from_model(job)


@app.get("/crawls", response_model=list[CrawlJobResponse])
def list_crawls(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[CrawlJobResponse]:
    """List crawl jobs (newest first)."""
    jobs = crawl_service.list_jobs(db, limit=limit, offset=offset)
    return [CrawlJobResponse.from_model(job) for job in jobs]


@app.get("/crawls/{job_id}", response_model=CrawlJobResponse)
def get_crawl(job_id: UUID, db: Session = Depends(get_db)) -> CrawlJobResponse:
    """Get a single crawl job by ID."""
    job = crawl_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return CrawlJobResponse.from_model(job)


@app.get(
    "/crawls/{job_id}/links",
    response_model=list[LinkRecord],
    responses={200: {"content": {"application/x-ndjson": {}}}},
)
def get_crawl_links(
    job_id: UUID,
    download: bool = False,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> object:
    """Return crawl links as JSON (parsed from the `links.jsonl` file)."""
    job = crawl_service.get_job(db, job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Links file not found")
    path = Path(job.result.links_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Links file missing on disk")

    if download:
        return FileResponse(path, media_type="application/x-ndjson", filename="links.jsonl")

    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 5000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    results: list[LinkRecord] = []
    skipped = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if skipped < offset:
                skipped += 1
                continue
            if len(results) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            results.append(
                LinkRecord(
                    url=record["url"],
                    depth=record["depth"],
                    parent=record.get("parent"),
                    status_code=record.get("status_code"),
                )
            )
    return results


@app.get("/crawls/{job_id}/links/file")
def download_crawl_links_file(job_id: UUID, db: Session = Depends(get_db)) -> FileResponse:
    """Download the raw links file (`links.jsonl`)."""
    job = crawl_service.get_job(db, job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Links file not found")
    path = Path(job.result.links_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Links file missing on disk")
    return FileResponse(path, media_type="application/x-ndjson", filename="links.jsonl")


@app.post(
    "/pipelines/crawl-scrape",
    response_model=CrawlScrapePipelineResponse,
    status_code=201,
)
def create_crawl_scrape_pipeline(
    payload: CrawlScrapePipelineRequest,
    db: Session = Depends(get_db),
) -> CrawlScrapePipelineResponse:
    """Create crawl + scrape jobs; reuse completed crawl or skip if already ingested."""
    vector_config = _vector_config_from_payload(payload)
    existing_crawl = crawl_service.find_completed_crawl_by_config(
        db,
        seed_url=payload.seed_url,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        crawl_mode=payload.mode,
    )

    if existing_crawl is not None:
        should_skip = False
        existing_scrape = None
        if payload.qdrant_collection:
            existing_scrape = scrape_service.find_completed_scrape_for_crawl(
                db,
                crawl_job_id=existing_crawl.id,
                embedding_source=payload.embedding_source,
                qdrant_collection=payload.qdrant_collection,
            )
            should_skip = existing_scrape is not None
        elif scrape_service.is_embedding_source_indexed(
            existing_crawl,
            payload.embedding_source,
        ):
            existing_scrape = scrape_service.find_completed_scrape_for_crawl(
                db,
                crawl_job_id=existing_crawl.id,
                embedding_source=payload.embedding_source,
            )
            should_skip = True

        if should_skip:
            logger.info(
                "crawl_scrape_pipeline_skipped crawl_job_id=%s embedding_source=%s collection=%s",
                existing_crawl.id,
                payload.embedding_source,
                payload.qdrant_collection,
            )
            skip_reason = (
                f"{payload.embedding_source} ingestion already completed for this crawl config"
            )
            if payload.qdrant_collection:
                skip_reason = (
                    f"{payload.embedding_source} already indexed to collection "
                    f"{payload.qdrant_collection} for this crawl config"
                )
            return CrawlScrapePipelineResponse(
                crawl_job=CrawlJobResponse.from_model(existing_crawl),
                scrape_job=ScrapeJobResponse.from_model(existing_scrape) if existing_scrape else None,
                skipped=True,
                skip_reason=skip_reason,
            )

    if existing_crawl is not None:
        crawl_job = existing_crawl
        try:
            scrape_job = scrape_service.create_pending_scrape_job(
                db,
                crawl_job_id=crawl_job.id,
                embedding_source=payload.embedding_source,
                **vector_config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        db.commit()
        logger.info(
            "crawl_scrape_pipeline_reused_crawl crawl_job_id=%s scrape_job_id=%s embedding_source=%s collection=%s",
            crawl_job.id,
            scrape_job.id,
            payload.embedding_source,
            payload.qdrant_collection,
        )
        enqueue_scrape(scrape_job.id)

        crawl_job = crawl_service.get_job(db, crawl_job.id)
        scrape_job = scrape_service.get_job(db, scrape_job.id)
        assert crawl_job is not None
        assert scrape_job is not None
        return CrawlScrapePipelineResponse(
            crawl_job=CrawlJobResponse.from_model(crawl_job),
            scrape_job=ScrapeJobResponse.from_model(scrape_job),
            skipped=False,
        )

    crawl_job = crawl_service.create_crawl_job(
        db,
        seed_url=payload.seed_url,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        crawl_mode=payload.mode,
    )
    try:
        scrape_job = scrape_service.create_pending_scrape_job(
            db,
            crawl_job_id=crawl_job.id,
            embedding_source=payload.embedding_source,
            **vector_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    logger.info(
        "crawl_scrape_pipeline_created crawl_job_id=%s scrape_job_id=%s seed_url=%s mode=%s collection=%s",
        crawl_job.id,
        scrape_job.id,
        payload.seed_url,
        payload.mode,
        payload.qdrant_collection,
    )
    enqueue_crawl_and_scrape(crawl_job.id, scrape_job.id)

    crawl_job = crawl_service.get_job(db, crawl_job.id)
    scrape_job = scrape_service.get_job(db, scrape_job.id)
    assert crawl_job is not None
    assert scrape_job is not None
    return CrawlScrapePipelineResponse(
        crawl_job=CrawlJobResponse.from_model(crawl_job),
        scrape_job=ScrapeJobResponse.from_model(scrape_job),
        skipped=False,
    )


@app.post("/scrapes", response_model=ScrapeJobResponse, status_code=201)
def create_scrape(payload: ScrapeCreateRequest, db: Session = Depends(get_db)) -> ScrapeJobResponse:
    """Create a scrape job from a completed crawl job and enqueue it."""
    try:
        job = scrape_service.create_scrape_job(
            db,
            crawl_job_id=payload.crawl_job_id,
            embedding_source=payload.embedding_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    logger.info("scrape_job_created id=%s crawl_job_id=%s", job.id, job.crawl_job_id)
    enqueue_scrape(job.id)
    job = scrape_service.get_job(db, job.id)
    assert job is not None
    return ScrapeJobResponse.from_model(job)


# --- NEW ENDPOINT 1: LIST SCRAPE JOBS ---

@app.get("/scrapes", response_model=list[ScrapeJobResponse])
def list_scrapes(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[ScrapeJobResponse]:
    """List scrape jobs (newest first) matching pagination criteria."""
    # Matches list implementation architecture of list_crawls
    jobs = scrape_service.list_scrapes(db, limit=limit, offset=offset)
    return [ScrapeJobResponse.from_model(job) for job in jobs]


@app.get("/scrapes/{job_id}", response_model=ScrapeJobResponse)
def get_scrape(job_id: UUID, db: Session = Depends(get_db)) -> ScrapeJobResponse:
    """Get a single scrape job by ID."""
    job = scrape_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return ScrapeJobResponse.from_model(job)


# --- NEW ENDPOINT 2: RETRIEVE CROSS-MODAL CHUNKS FROM QDRANT ---
@app.post("/scrapes/query", response_model=list[RAGChunkItem])
def query_vector_chunks(payload: RAGQueryRequest) -> list[RAGChunkItem]:
    """Search stored chunks with dense, sparse, or hybrid retrieval."""
    settings = get_settings()

    try:
        hits = search_scrape_chunks(
            settings,
            query_text=payload.text_query,
            limit=payload.limit,
            mode=payload.mode,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
        return [
            RAGChunkItem(
                id=str(hit["id"]),
                score=float(hit["score"]),
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
    except Exception as exc:
        logger.error("vector_search_endpoint_failed error=%s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector retrieval failure: {str(exc)}") from exc
        
def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)