import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from src.ingestion_service.vector.search import search_document_chunks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.routes.knowledge_products import (
    product_chunk_strategy,
    product_text_embedding_model,
)
from src.file_manager.core.errors import ConflictError, NotFoundError, ValidationError
from src.ingestion_service.utils.validation import validate_description, validate_qdrant_collection
from src.shared.config.settings import get_settings
from src.shared.db.models import IndexModality, JobStatus, KnowledgeProduct, Pipeline, PipelineRun, PipelineSource, RagStrategy, IndexedFile
from src.shared.db.session import get_db
from src.shared.queue.client import enqueue_pipeline_run, enqueue_sync_run

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])

SCRAPER_MODES = ("httpx", "playwright", "auto")

# ── Assistant pipelines ──────────────────────────────────────────────────────
# A pipeline whose strategy names a store an assistant reads is an assistant.
# It owns no documents: it reads the Knowledge Product's stores, and the
# retrieval manager addresses it by slug.
STRATEGY_DESTINATION = {
    "vector": "vector_qdrant",
    "lexical": "lexical_opensearch",
    "relational": "relational_pgvector",
}
# Ordered as the create form shows them. "hybrid" needs two stores, so it is
# handled separately from the single-store strategies above.
ASSISTANT_STRATEGIES = ("vector", "lexical", "relational", "hybrid")
HYBRID_DESTINATIONS = ("vector_qdrant", "lexical_opensearch")
RETRIEVAL_DESTINATION_TYPES = tuple(STRATEGY_DESTINATION.values())

_STRATEGY_LITERAL = Literal[
    "naive", "sparse", "hybrid", "multimodal", "metadata", "vector", "lexical", "relational"
]


def slugify_pipeline_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].strip("-")
    return slug or "assistant"


def is_assistant_strategy(strategy: str) -> bool:
    return strategy in ASSISTANT_STRATEGIES


def enabled_retrieval_destinations(product: KnowledgeProduct) -> set[str]:
    """The product's enabled destination types that an assistant can read."""
    return {
        d.destination_type
        for d in (product.destinations or [])
        if d.enabled and d.destination_type in RETRIEVAL_DESTINATION_TYPES
    }


class PipelineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=8, max_length=512)
    rag_strategy: _STRATEGY_LITERAL
    embedding_model: str = Field(min_length=1, max_length=128)
    sparse_embedding_model: str | None = Field(default=None, max_length=128)
    modality: Literal["text", "image"] | None = None
    directory_names: list[str] = Field(default_factory=list)
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    qdrant_collection: str | None = Field(default=None, max_length=128)
    web_scraper_enabled: bool = False
    scraper_seed_url: str | None = None
    scraper_max_depth: int = Field(default=2, ge=0)
    scraper_max_pages: int = Field(default=50, ge=1)
    scraper_mode: Literal["httpx", "playwright", "auto"] = "httpx"
    knowledge_product_id: str | None = None
    # Assistant fields. The slug is derived from the name when omitted.
    slug: str | None = Field(default=None, max_length=64)
    chat_model: str | None = Field(default=None, max_length=128)
    prompt_template_id: uuid.UUID | None = None
    guardrails_config_id: uuid.UUID | None = None

    @field_validator("directory_names")
    @classmethod
    def normalize_dirs(cls, v: list[str]) -> list[str]:
        return [d.strip().lower() for d in v if d.strip()]

    @field_validator("qdrant_collection")
    @classmethod
    def check_collection(cls, v: str | None) -> str | None:
        return validate_qdrant_collection(v) if v else None

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
    # Assistant fields. Every component stays editable after creation.
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    slug: str | None = Field(default=None, max_length=64)
    rag_strategy: _STRATEGY_LITERAL | None = None
    chat_model: str | None = Field(default=None, max_length=128)
    prompt_template_id: uuid.UUID | None = None
    guardrails_config_id: uuid.UUID | None = None
    knowledge_product_id: uuid.UUID | None = None
    embedding_model: str | None = Field(default=None, max_length=128)

    @field_validator("directory_names")
    @classmethod
    def normalize_dirs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [d.strip().lower() for d in v if d.strip()]


def _pipeline_to_dict(p: Pipeline) -> dict:
    product = p.knowledge_product
    return {
        "id": str(p.id),
        "knowledge_product_id": str(p.knowledge_product_id) if p.knowledge_product_id else None,
        "name": p.name,
        "slug": p.slug,
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
        "chat_model": p.chat_model,
        "prompt_template_id": str(p.prompt_template_id) if p.prompt_template_id else None,
        "guardrails_config_id": (
            str(p.guardrails_config_id) if p.guardrails_config_id else None
        ),
        "is_assistant": is_assistant_strategy(p.rag_strategy.value),
        # The retrieval manager resolves this pipeline's stores from here, so one
        # call answers both "how do I reach this assistant" and "what does it read".
        "knowledge_product": (
            {
                "id": str(product.id),
                "name": product.name,
                "status": product.status,
                "chunk_strategy": product_chunk_strategy(product),
                "text_embedding_model": product_text_embedding_model(product),
                "destinations": [
                    {
                        "destination_type": d.destination_type,
                        "enabled": d.enabled,
                        "config": d.config or {},
                    }
                    for d in sorted(product.destinations or [], key=lambda d: d.destination_type)
                ],
            }
            if product
            else None
        ),
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


def _validate_assistant_options(
    strategy: str, chat_model: str | None, product: KnowledgeProduct
) -> None:
    """Check the stores an assistant strategy needs are enabled on the product."""
    if not chat_model:
        raise ValidationError("CHAT_MODEL_REQUIRED", "Select a chat model for the assistant.")
    available = enabled_retrieval_destinations(product)
    if not available:
        raise ValidationError(
            "NO_RETRIEVAL_DESTINATION",
            "This Knowledge Product has no enabled retrieval destination. "
            "Enable Qdrant, OpenSearch or PostgreSQL in the Ingestion Manager.",
            {"knowledge_product_id": str(product.id)},
        )
    if strategy == "hybrid":
        missing = [d for d in HYBRID_DESTINATIONS if d not in available]
    else:
        needed = STRATEGY_DESTINATION[strategy]
        missing = [] if needed in available else [needed]
    if missing:
        raise ValidationError(
            "RAG_STRATEGY_UNAVAILABLE",
            f"The '{strategy}' strategy needs an enabled {', '.join(missing)} destination.",
            {"missing_destinations": missing, "available": sorted(available)},
        )


def _validate_create(
    body: PipelineCreateRequest, product: KnowledgeProduct | None = None
) -> None:
    if is_assistant_strategy(body.rag_strategy):
        if product is None:
            raise ValidationError(
                "KNOWLEDGE_PRODUCT_NOT_FOUND",
                "Select a Knowledge Product for the assistant.",
            )
        _validate_assistant_options(body.rag_strategy, body.chat_model, product)
        return

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
    if not body.qdrant_collection:
        raise ValidationError("COLLECTION_REQUIRED", "Provide a Qdrant collection name.")
    if not body.directory_names and not body.web_scraper_enabled:
        raise ValidationError(
            "NO_SOURCES",
            "Select at least one folder or enable web scraper.",
        )
    if body.web_scraper_enabled and not body.scraper_seed_url:
        raise ValidationError("SCRAPER_URL_REQUIRED", "Web scraper requires a seed URL.")


async def _load_knowledge_product(
    db: AsyncSession, product_id: str | uuid.UUID | None
) -> KnowledgeProduct | None:
    if not product_id:
        return None
    try:
        key = product_id if isinstance(product_id, uuid.UUID) else uuid.UUID(str(product_id))
    except ValueError:
        raise ValidationError("KNOWLEDGE_PRODUCT_NOT_FOUND", "Knowledge Product id is not valid.")
    return await db.get(KnowledgeProduct, key)


async def _unique_slug(db: AsyncSession, base: str, exclude_id: uuid.UUID | None = None) -> str:
    """The slug addresses the assistant in a URL, so it has to be unique."""
    slug = slugify_pipeline_name(base)
    if not slug:
        slug = "assistant"
    candidate = slug
    n = 2
    while True:
        stmt = select(Pipeline).where(Pipeline.slug == candidate)
        if exclude_id is not None:
            stmt = stmt.where(Pipeline.id != exclude_id)
        if not (await db.execute(stmt)).scalar_one_or_none():
            return candidate
        candidate = f"{slug}-{n}"
        n += 1


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
    pipelines = list(result.scalars().all())
    
    unlinked = [p for p in pipelines if p.knowledge_product_id is None]
    if unlinked:
        kp_res = await db.execute(select(KnowledgeProduct).order_by(KnowledgeProduct.created_at.asc()).limit(1))
        default_kp = kp_res.scalar_one_or_none()
        if default_kp:
            for p in unlinked:
                p.knowledge_product_id = default_kp.id
            await db.commit()

    return [_pipeline_to_dict(p) for p in pipelines]


@router.post("", status_code=201)
async def create_pipeline(body: PipelineCreateRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    assistant = is_assistant_strategy(body.rag_strategy)
    product = await _load_knowledge_product(db, body.knowledge_product_id)
    if assistant and body.knowledge_product_id and product is None:
        raise ValidationError("KNOWLEDGE_PRODUCT_NOT_FOUND", "Knowledge Product not found.")
    _validate_create(body, product)

    for field, value in [("name", body.name), ("description", body.description)]:
        col = Pipeline.name if field == "name" else Pipeline.description
        existing = await db.execute(select(Pipeline).where(col == value))
        if existing.scalar_one_or_none():
            raise ConflictError(
                "PIPELINE_EXISTS",
                f"A pipeline with this {field} already exists.",
            )

    if body.qdrant_collection:
        existing_col = await db.execute(
            select(Pipeline).where(Pipeline.qdrant_collection == body.qdrant_collection)
        )
        if existing_col.scalar_one_or_none():
            raise ConflictError(
                "COLLECTION_EXISTS",
                "This Qdrant collection name is already used by another pipeline.",
            )

    kp_id: uuid.UUID | None = None
    slug: str | None = None
    if assistant:
        kp_id = product.id
        slug = await _unique_slug(db, body.slug or body.name)
    elif body.knowledge_product_id:
        kp_id = uuid.UUID(body.knowledge_product_id)
    else:
        kp_res = await db.execute(select(KnowledgeProduct).order_by(KnowledgeProduct.created_at.asc()).limit(1))
        default_kp = kp_res.scalar_one_or_none()
        if default_kp:
            kp_id = default_kp.id

    pipeline = Pipeline(
        knowledge_product_id=kp_id,
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
        slug=slug,
        chat_model=body.chat_model,
        prompt_template_id=body.prompt_template_id,
        guardrails_config_id=body.guardrails_config_id,
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


@router.get("/by-slug/{slug}", status_code=200)
async def get_pipeline_by_slug(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Resolve a pipeline by its external slug.

    Declared before ``/{pipeline_id}`` on purpose: FastAPI matches routes in
    declaration order, so a later declaration makes "by-slug" parse as a UUID.
    """
    result = await db.execute(select(Pipeline).where(Pipeline.slug == slug))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise NotFoundError(
            "PIPELINE_NOT_FOUND",
            "No pipeline has this slug.",
            {"slug": slug},
        )
    return _pipeline_to_dict(pipeline)


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

    # ``exclude_unset`` separates "the client did not send this key" from "the
    # client sent null". The two optional attachments use it: sending null
    # clears the attachment, which is how the form removes one.
    sent = body.model_dump(exclude_unset=True)
    if "prompt_template_id" in sent:
        pipeline.prompt_template_id = sent["prompt_template_id"]
    if "guardrails_config_id" in sent:
        pipeline.guardrails_config_id = sent["guardrails_config_id"]

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

    if body.name is not None:
        clash = await db.execute(
            select(Pipeline).where(Pipeline.name == body.name, Pipeline.id != pipeline_id)
        )
        if clash.scalar_one_or_none():
            raise ConflictError("PIPELINE_EXISTS", "A pipeline with this name already exists.")
        pipeline.name = body.name
    if body.description is not None:
        pipeline.description = validate_description(body.description)
    if body.slug is not None:
        pipeline.slug = await _unique_slug(db, body.slug, exclude_id=pipeline_id)

    # A different strategy or product can drop the stores the assistant reads,
    # so those two re-run the create-time checks.
    next_strategy = body.rag_strategy or pipeline.rag_strategy.value
    if is_assistant_strategy(next_strategy) and (
        body.rag_strategy is not None or body.knowledge_product_id is not None
    ):
        product = await _load_knowledge_product(
            db, body.knowledge_product_id or pipeline.knowledge_product_id
        )
        if product is None:
            raise ValidationError(
                "KNOWLEDGE_PRODUCT_NOT_FOUND", "Select a Knowledge Product for the assistant."
            )
        _validate_assistant_options(
            next_strategy, body.chat_model or pipeline.chat_model, product
        )
        pipeline.knowledge_product_id = product.id

    if body.rag_strategy is not None:
        pipeline.rag_strategy = RagStrategy(body.rag_strategy)
    if pipeline.slug is None and is_assistant_strategy(pipeline.rag_strategy.value):
        pipeline.slug = await _unique_slug(db, pipeline.name, exclude_id=pipeline_id)
    if body.chat_model is not None:
        pipeline.chat_model = body.chat_model
    if body.embedding_model is not None:
        pipeline.embedding_model = body.embedding_model

    await db.commit()
    await db.refresh(pipeline)
    return _pipeline_to_dict(pipeline)
@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline:
        raise NotFoundError("PIPELINE_NOT_FOUND", "Pipeline not found.")
    await db.execute(delete(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id))
    await db.execute(delete(PipelineSource).where(PipelineSource.pipeline_id == pipeline_id))
    await db.delete(pipeline)
    await db.commit()
    return None


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
