import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from src.ingestion_service.vector.search import search_document_chunks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.ingestion_service.utils.validation import validate_description, validate_qdrant_collection
from src.shared.config.settings import get_settings
from src.shared.db.models import IndexModality, JobStatus, Pipeline, PipelineRun, RagStrategy, IndexedFile
from src.shared.db.session import get_db
from src.shared.queue.client import enqueue_pipeline_run, enqueue_sync_run

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

SCRAPER_MODES = ("httpx", "playwright", "auto")


class PipelineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=8, max_length=512)
    rag_strategy: Literal["naive", "sparse", "hybrid", "multimodal", "metadata"]
    embedding_model: str = Field(min_length=1, max_length=128)
    sparse_embedding_model: str | None = Field(default=None, max_length=128)
    modality: Literal["text", "image"] | None = None
    directory_names: list[str] = Field(default_factory=list)
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    qdrant_collection: str = Field(min_length=3, max_length=128)
    web_scraper_enabled: bool = False
    scraper_seed_url: str | None = None
    scraper_max_depth: int = Field(default=2, ge=0)
    scraper_max_pages: int = Field(default=50, ge=1)
    scraper_mode: Literal["httpx", "playwright", "auto"] = "httpx"

    @field_validator("directory_names")
    @classmethod
    def normalize_dirs(cls, v: list[str]) -> list[str]:
        return [d.strip().lower() for d in v if d.strip()]

    @field_validator("qdrant_collection")
    @classmethod
    def check_collection(cls, v: str) -> str:
        return validate_qdrant_collection(v)

    @field_validator("description")
    @classmethod
    def check_description(cls, v: str) -> str:
        return validate_description(v)


class PipelinePatchRequest(BaseModel):
    directory_names: list[str] | None = None
    web_scraper_enabled: bool | None = None
    scraper_seed_url: str | None = None
    scraper_max_depth: int | None = None
    scraper_max_pages: int | None = None

    @field_validator("directory_names")
    @classmethod
    def normalize_dirs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [d.strip().lower() for d in v if d.strip()]


def _pipeline_to_dict(p: Pipeline) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "rag_strategy": p.rag_strategy.value,
        "embedding_model": p.embedding_model,
        "sparse_embedding_model": p.sparse_embedding_model,
        "modality": p.modality.value if p.modality else None,
        "directory_names": p.directory_names or [],
        "chunk_size": p.chunk_size,
        "chunk_overlap": p.chunk_overlap,
        "qdrant_collection": p.qdrant_collection,
        "web_scraper_enabled": p.web_scraper_enabled,
        "scraper_seed_url": p.scraper_seed_url,
        "scraper_max_depth": p.scraper_max_depth,
        "scraper_max_pages": p.scraper_max_pages,
        "scraper_mode": p.scraper_mode,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _run_to_dict(r: PipelineRun) -> dict:
    return {
        "id": str(r.id),
        "pipeline_id": str(r.pipeline_id),
        "status": r.status.value,
        "files_total": r.files_total,
        "files_processed": r.files_processed,
        "pages_indexed": r.pages_indexed,
        "points_upserted": r.points_upserted,
        "scraper_crawl_job_id": r.scraper_crawl_job_id,
        "scraper_scrape_job_id": r.scraper_scrape_job_id,
        "error_message": r.error_message,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _validate_create(body: PipelineCreateRequest) -> None:
    if body.rag_strategy in {"multimodal", "metadata"} and not body.modality:
        raise ValidationError(
            "MODALITY_REQUIRED",
            "Multimodal and metadata strategies require modality (text or image).",
        )
    if body.rag_strategy in {"sparse", "hybrid"} and not body.sparse_embedding_model:
        raise ValidationError(
            "SPARSE_MODEL_REQUIRED",
            "Sparse and hybrid strategies require sparse_embedding_model.",
        )
    if not body.directory_names and not body.web_scraper_enabled:
        raise ValidationError(
            "NO_SOURCES",
            "Select at least one folder or enable web scraper.",
        )
    if body.web_scraper_enabled and not body.scraper_seed_url:
        raise ValidationError("SCRAPER_URL_REQUIRED", "Web scraper requires a seed URL.")


@router.get("/options", status_code=200)
async def pipeline_options():
    settings = get_settings()
    return {
        "rag_strategies": [
            {"id": "naive", "label": "Standard", "description": "Standard text understanding"},
            {"id": "sparse", "label": "Keyword", "description": "Exact keyword matching"},
            {"id": "hybrid", "label": "Advanced Hybrid", "description": "Combines meaning and keyword search"},
            {"id": "multimodal", "label": "Visual & Text", "description": "Processes both text and images"},
            {"id": "metadata", "label": "Advanced Metadata", "description": "Rich data storage for filtering"},
        ],
        "modalities": [
            {"id": "text", "label": "Text", "description": "Process standard text documents"},
            {"id": "image", "label": "Visual", "description": "Capture and process visual pages"},
        ],
        "suggested_embedding_models": settings.unique_embedding_models,
        "suggested_sparse_models": [settings.sparse_embedding_model],
        "scraper_modes": list(SCRAPER_MODES),
        "collection_naming_hint": "Use a unique name per pipeline, e.g. legal-docs-hybrid-v1",
    }


@router.get("/catalog", status_code=200)
async def pipeline_catalog(db: Annotated[AsyncSession, Depends(get_db)]):
    """Lightweight list for chat UI — select pipeline by description, not UUID."""
    result = await db.execute(
        select(Pipeline).order_by(Pipeline.description.asc())
    )
    return [
        {
            "description": p.description,
            "name": p.name,
            "rag_strategy": p.rag_strategy.value,
            "qdrant_collection": p.qdrant_collection,
            "embedding_model": p.embedding_model,
            "id": str(p.id),
        }
        for p in result.scalars().all()
    ]


@router.get("/by-description", status_code=200)
async def get_pipeline_by_description(
    db: Annotated[AsyncSession, Depends(get_db)],
    description: str = Query(min_length=8),
):
    result = await db.execute(
        select(Pipeline).where(Pipeline.description == description.strip())
    )
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise NotFoundError(
            "PIPELINE_NOT_FOUND",
            "No pipeline matches this description.",
            {"description": description},
        )
    return _pipeline_to_dict(pipeline)


@router.get("", status_code=200)
async def list_pipelines(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(Pipeline).order_by(Pipeline.created_at.desc()))
    return [_pipeline_to_dict(p) for p in result.scalars().all()]


@router.post("", status_code=201)
async def create_pipeline(body: PipelineCreateRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    _validate_create(body)

    for field, value in [("name", body.name), ("description", body.description)]:
        col = Pipeline.name if field == "name" else Pipeline.description
        existing = await db.execute(select(Pipeline).where(col == value))
        if existing.scalar_one_or_none():
            raise ConflictError(
                "PIPELINE_EXISTS",
                f"A pipeline with this {field} already exists.",
            )

    existing_col = await db.execute(
        select(Pipeline).where(Pipeline.qdrant_collection == body.qdrant_collection)
    )
    if existing_col.scalar_one_or_none():
        raise ConflictError(
            "COLLECTION_EXISTS",
            "This Qdrant collection name is already used by another pipeline.",
        )

    pipeline = Pipeline(
        name=body.name,
        description=body.description,
        rag_strategy=RagStrategy(body.rag_strategy),
        embedding_model=body.embedding_model,
        sparse_embedding_model=body.sparse_embedding_model,
        modality=IndexModality(body.modality) if body.modality else None,
        directory_names=body.directory_names,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        qdrant_collection=body.qdrant_collection,
        web_scraper_enabled=body.web_scraper_enabled,
        scraper_seed_url=body.scraper_seed_url,
        scraper_max_depth=body.scraper_max_depth,
        scraper_max_pages=body.scraper_max_pages,
        scraper_mode=body.scraper_mode,
    )
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return _pipeline_to_dict(pipeline)


@router.get("/runs", status_code=200)
async def list_all_pipeline_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
):
    """All runs across all pipelines, newest first, with pipeline name attached."""
    result = await db.execute(
        select(PipelineRun)
        .options(selectinload(PipelineRun.pipeline))
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
    )
    rows = []
    for run in result.scalars().all():
        data = _run_to_dict(run)
        if run.pipeline:
            data["pipeline_name"] = run.pipeline.name
            data["pipeline_description"] = run.pipeline.description
            data["qdrant_collection"] = run.pipeline.qdrant_collection
        rows.append(data)
    return rows


@router.get("/runs/{run_id}", status_code=200)
async def get_pipeline_run(run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    run = await db.get(PipelineRun, run_id, options=(selectinload(PipelineRun.pipeline),))
    if not run:
        raise NotFoundError("RUN_NOT_FOUND", "Pipeline run not found.")
    data = _run_to_dict(run)
    if run.pipeline:
        data["pipeline_name"] = run.pipeline.name
        data["pipeline_description"] = run.pipeline.description
        data["qdrant_collection"] = run.pipeline.qdrant_collection
    return data


@router.get("/{pipeline_id}", status_code=200)
async def get_pipeline(pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")
    return _pipeline_to_dict(pipeline)


@router.patch("/{pipeline_id}", status_code=200)
async def update_pipeline(
    pipeline_id: uuid.UUID, body: PipelinePatchRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    if body.directory_names is not None:
        pipeline.directory_names = body.directory_names
    if body.web_scraper_enabled is not None:
        pipeline.web_scraper_enabled = body.web_scraper_enabled
    if body.scraper_seed_url is not None:
        pipeline.scraper_seed_url = body.scraper_seed_url
    if body.scraper_max_depth is not None:
        pipeline.scraper_max_depth = body.scraper_max_depth
    if body.scraper_max_pages is not None:
        pipeline.scraper_max_pages = body.scraper_max_pages

    await db.commit()
    await db.refresh(pipeline)
    return _pipeline_to_dict(pipeline)


@router.get("/{pipeline_id}/stats", status_code=200)
async def get_pipeline_stats(
    pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    from sqlalchemy import func
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    # Get total indexed files from our tracking table
    files_result = await db.execute(
        select(func.count()).where(IndexedFile.pipeline_id == pipeline_id)
    )
    indexed_files_count = files_result.scalar() or 0

    # Get latest pages indexed from latest scraper run
    pages_result = await db.execute(
        select(PipelineRun.pages_indexed)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.created_at.desc())
        .limit(1)
    )
    pages_indexed = pages_result.scalar() or 0

    return {
        "pipeline_id": str(pipeline_id),
        "indexed_files_count": indexed_files_count,
        "scraped_pages_count": pages_indexed,
    }


@router.post("/{pipeline_id}/run", status_code=202)
async def start_pipeline(pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    active = await db.execute(
        select(PipelineRun).where(
            PipelineRun.pipeline_id == pipeline_id,
            PipelineRun.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
        )
    )
    if active.scalar_one_or_none():
        raise ConflictError("PIPELINE_RUNNING", "This pipeline already has an active run.")

    run = PipelineRun(pipeline_id=pipeline.id, status=JobStatus.PENDING)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await enqueue_pipeline_run(run.id)
    return _run_to_dict(run)


@router.get("/{pipeline_id}/runs", status_code=200)
async def list_pipeline_runs(pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")
    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.created_at.desc())
    )
    return [_run_to_dict(r) for r in result.scalars().all()]


@router.post("/{pipeline_id}/sync", status_code=202)
async def trigger_pipeline_sync(
    pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Manually trigger a file-sync for this pipeline."""
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")
    if not pipeline.directory_names:
        raise ValidationError(
            "NO_DIRECTORIES",
            "Pipeline has no directories configured for sync.",
        )

    # Prevent overlapping syncs
    active = await db.execute(
        select(PipelineRun).where(
            PipelineRun.pipeline_id == pipeline_id,
            PipelineRun.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
        )
    )
    if active.scalar_one_or_none():
        raise ConflictError("SYNC_RUNNING", "This pipeline already has an active run.")

    await enqueue_sync_run(pipeline.id)
    return {"status": "queued", "pipeline_id": str(pipeline.id)}


@router.get("/{pipeline_id}/sync-status", status_code=200)
async def get_pipeline_sync_status(
    pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
):
    """Return the latest pipeline run (which may be a sync run)."""
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")

    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        return {"status": "no_runs", "pipeline_id": str(pipeline_id)}
    return _run_to_dict(run)


class RAGQueryRequest(BaseModel):
    text_query: str = Field(..., description="The semantic search question text.")
    collection: str | None = Field(default=None, description="Qdrant collection to search. If omitted, uses default.")
    limit: int = Field(default=5, ge=1, le=50, description="Number of items to retrieve.")
    mode: Literal["hybrid", "dense", "sparse"] = Field(
        default="hybrid",
        description="Search mode: hybrid (RRF), dense, or sparse.",
    )
    source_type: Literal["all", "web_scrape", "file_ingest"] = Field(
        default="all",
        description="Filter by ingest source: all, web_scrape, or file_ingest.",
    )
    source_id: str | None = Field(
        default=None,
        description="Optional job/document id to scope retrieval (scrape_job_id or pipeline run id).",
    )
    pipeline_id: str | None = Field(default=None, description="Optional pipeline id to scope search.")
    file_id: str | None = Field(default=None, description="Optional file id to scope search.")
    directory_name: str | None = Field(default=None, description="Optional directory name filter.")
    original_name: str | None = Field(default=None, description="Optional file name filter.")
    mime_type: str | None = Field(default=None, description="Optional mime type filter.")
    rag_strategy: str | None = Field(default=None, description="Optional RAG strategy filter.")


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
    file_id: str | None = None
    directory_name: str | None = None
    original_name: str | None = None
    page_index: int | None = None


@router.post("/query", response_model=list[RAGChunkItem])
async def query_pipeline_chunks(payload: RAGQueryRequest) -> list[RAGChunkItem]:
    """Search stored document/web scraper chunks with dense, sparse or hybrid retrieval modes + metadata filters."""
    try:
        hits = search_document_chunks(
            query_text=payload.text_query,
            collection=payload.collection,
            limit=payload.limit,
            mode=payload.mode,
            source_type=payload.source_type,
            source_id=payload.source_id,
            pipeline_id=payload.pipeline_id,
            file_id=payload.file_id,
            directory_name=payload.directory_name,
            original_name=payload.original_name,
            mime_type=payload.mime_type,
            rag_strategy=payload.rag_strategy,
        )
        return [RAGChunkItem(**hit) for hit in hits]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Vector retrieval failure: {str(exc)}"
        ) from exc
