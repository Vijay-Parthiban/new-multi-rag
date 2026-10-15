"""Universal RAG Ingestion Multi-Sink Fanout Engine.

Transforms raw documents from linked MinIO source buckets and fans out
index artifacts across 4 destination categories:
1. Vector Engine — Qdrant
2. Lexical Engine — OpenSearch (BM25 + Sparse SPLADE)
3. Multi-Model Relational Database — PostgreSQL (pgvector / pgvectorscale)
4. Semantic Cache & Summary Stores — RedisVL (RAPTOR summary trees, parent-child maps)

Adding a destination means adding one writer and one purger to ``_WRITERS`` and
``_PURGERS``, plus one entry in ``knowledge_destination_schemas``.
"""

import asyncio
import base64
import hashlib
import logging
import re
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion_service.core.knowledge_events import publish
from src.ingestion_service.core.page_yielder import FilePage, iter_file_pages
from src.ingestion_service.core.webscrape import drop_webscrape_control_objects
from src.ingestion_service.embeddings.client import EmbeddingClient
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE
from src.ingestion_service.utils.text_splitter import (
    ChunkPlan,
    adjacent_similarities,
    chunk_page,
    chunk_parent_child,
    chunk_sentence_window,
    chunk_text,
    chunk_textual,
    sentence_splitter,
)
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore
from src.shared.config.settings import get_settings
from src.shared.db.models import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    DEFAULT_MODALITY_MODE,
    KnowledgeProduct,
    KnowledgeProductFile,
)
from src.shared.storage.s3_client import get_object, list_objects, put_object

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _resolve_opensearch_url(dest_config: dict[str, Any], settings: Any) -> str:
    """The OpenSearch endpoint, which is deployment configuration, not per product."""
    return settings.opensearch_url.rstrip("/")


def _resolve_pg_table(dest_config: dict[str, Any]) -> str:
    raw = dest_config.get("table_name") or dest_config.get("table_prefix") or "knowledge_chunks"
    # The table name comes from a stored destination config, so treat it as
    # untrusted: it is interpolated into SQL as an identifier.
    return raw if _IDENT_RE.match(str(raw)) else "knowledge_chunks"


def _pg_schema(dest_config: dict[str, Any]) -> str:
    """The product's Postgres schema, or ``public`` when unset or unsafe."""
    raw = str(dest_config.get("schema_name") or "public").strip().lower()
    if raw == "public" or not _IDENT_RE.match(raw):
        return "public"
    return raw


def _normalize_pg_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")


def pg_connection_urls(dest_config: dict[str, Any], settings: Any) -> list[str]:
    """Candidate Postgres URLs, best first.

    The ingestion database is the only configured source; the literal is the
    compose default for a dev deploy whose DATABASE_URL is SQLite. Non-Postgres
    URLs are dropped, because the dev default is SQLite and psycopg cannot open
    it.
    """
    candidates = [
        _normalize_pg_url(settings.database_url),
        "postgresql://ingestion:ingestion@localhost:5432/ingestion",
    ]
    return [c for c in candidates if c and c.startswith("postgresql://")]


def connect_pg(dest_config: dict[str, Any], settings: Any):
    """Open a psycopg connection to the first reachable candidate, or return None."""
    try:
        import psycopg2 as pg_driver
    except ImportError:
        import psycopg as pg_driver

    for url in pg_connection_urls(dest_config, settings):
        try:
            return pg_driver.connect(url)
        except Exception:
            continue
    return None


def _qualified_pg_table(dest_config: dict[str, Any]) -> str:
    table_name = _resolve_pg_table(dest_config)
    schema = _pg_schema(dest_config)
    if schema != "public":
        return f"{schema}.{table_name}"
    return table_name


def _opensearch_auth(dest_config: dict[str, Any]) -> tuple[str, str] | None:
    """Basic auth for OpenSearch, read from the deployment environment.

    Returns ``None`` when no username is configured, which sends no header.
    """
    settings = get_settings()
    if settings.opensearch_username:
        return settings.opensearch_username, settings.opensearch_password
    return None


def _redis_glob_escape(text: str) -> str:
    """Escape a literal key fragment for use inside a Redis KEYS glob."""
    return re.sub(r"([*?\[\]\\])", r"\\\1", text)


def _redis_prefix(dest_config: dict[str, Any]) -> str:
    return dest_config.get("index_prefix") or "knowledge_cache"


def _build_fanout_payload(
    *,
    source_id: uuid.UUID,
    product_id: uuid.UUID,
    file_key: str,
    page: FilePage,
) -> dict[str, Any]:
    file_name = Path(file_key).name
    page_text = (page.text or "").strip()
    # A page-image record keeps its page text in `content`, so every text-shaped
    # reader (the sources panel, the judge's context) still reads words. The bytes
    # ride in `image_base64`, which `image_data_uri` rebuilds on the reader side.
    is_page_image = page.modality == "image" and bool(page.image_png)
    content = page_text
    return {
        "source_type": FILE_INGEST_SOURCE_TYPE,
        "source_id": str(source_id),
        "source_locator": file_key,
        "file_key": file_key,
        "file_name": file_name,
        "original_name": file_name,
        "title": file_name,
        "page_index": page.page_index,
        "chunk_index": page.chunk_index,
        "modality": page.modality,
        "image_ref": page.image_ref,
        # "chunk" for a normal chunk, "parent" or "child" under the parent_child
        # strategy. parent_ref resolves to the parent record in the same file.
        "record_type": page.record_type,
        "parent_ref": page.parent_ref,
        # A page image is type "image", which is how a reader tells it apart and
        # sends the bytes to a vision model. Its text stays in `text`.
        "type": "image" if is_page_image else "text",
        "content": content,
        "text": page_text,
        "image_base64": (
            base64.b64encode(page.image_png).decode("ascii") if is_page_image else None
        ),
        "mime_type": "image/png" if is_page_image else None,
        "knowledge_product_id": str(product_id),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _resolve_chunking(product: Any) -> tuple[int, int]:
    """Chunk size and overlap for this product, from its Ingestion Profile.

    A product with no profile keeps the values the Pipeline form uses, so an old
    product behaves like the old default.
    """
    profile = getattr(product, "ingestion_profile", None)
    if profile is None:
        return DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP
    size = int(profile.chunk_size or DEFAULT_CHUNK_SIZE)
    overlap = int(profile.chunk_overlap or DEFAULT_CHUNK_OVERLAP)
    # A stored row could predate the API bound, and an overlap at or above the
    # size would emit chunks wider than the window.
    return size, min(overlap, max(0, size - 1))


def _resolve_chunk_strategy(product: Any) -> str:
    """The chunk strategy this product's profile names, or the original one.

    ``recursive`` is the algorithm that shipped first, so a product with no
    profile chunks exactly as it did before the strategy select existed.
    """
    profile = getattr(product, "ingestion_profile", None)
    if profile is None:
        return DEFAULT_CHUNK_STRATEGY
    mode = getattr(profile, "chunk_strategy", None)
    if mode is None:
        return DEFAULT_CHUNK_STRATEGY
    value = mode.value if hasattr(mode, "value") else str(mode)
    return value or DEFAULT_CHUNK_STRATEGY


def _resolve_chunk_config(product: Any) -> dict[str, Any]:
    """The selected strategy's own settings, from this product's profile.

    The catalogue in ``apps/api/routes/chunk_strategies.py`` names every key, and
    the profile API checks the values, so this reads without validating. The
    chunker clamps each value again, because a stored row can predate a bound.
    """
    profile = getattr(product, "ingestion_profile", None)
    stored = getattr(profile, "chunk_config", None) if profile else None
    return dict(stored or {})


def _setting_int(config: dict[str, Any] | None, key: str, default: int) -> int:
    """One numeric strategy setting, or the default when it is absent or unreadable."""
    raw = (config or {}).get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _context_similarities(
    pages: list[FilePage], *, model: str, settings: Any
) -> dict[int, list[float]]:
    """Cosine similarity of each adjacent sentence pair, per page index.

    One batch embedding request per page, not one per sentence. Returns an empty
    dict when the model is unreachable, and ``context_aware`` then falls back to
    the size window alone instead of failing the file.
    """
    targets = {
        page.page_index: sentence_splitter(page.text or "")
        for page in pages
        if len(page.text or "") > 0
    }
    targets = {index: units for index, units in targets.items() if len(units) > 1}
    if not targets:
        return {}
    flat = [unit for units in targets.values() for unit in units]
    embedder = EmbeddingClient(
        base_url=settings.litellm_base_url, api_key=settings.openai_api_key, model=model
    )
    try:
        vectors = embedder.embed_passages(flat)
    except Exception as exc:
        logger.warning("chunk_strategy_similarity_failed model=%s error=%s", model, exc)
        return {}
    if len(vectors) != len(flat):
        logger.warning(
            "chunk_strategy_similarity_mismatch expected=%d got=%d", len(flat), len(vectors)
        )
        return {}
    out: dict[int, list[float]] = {}
    cursor = 0
    for index, units in targets.items():
        group = vectors[cursor : cursor + len(units)]
        cursor += len(units)
        out[index] = adjacent_similarities(group)
    return out


CONTEXT_PROMPT = (
    "Place the excerpt in the page. Write one sentence of at most 30 words that says what "
    "the excerpt is about and where it sits, so the excerpt reads on its own in a search "
    "result. Answer with the sentence alone. Add no commentary."
)


def _context_sentence(
    page_text: str, chunk: str, *, model: str, max_tokens: int, settings: Any
) -> str:
    """One chat call for one chunk. Raises on a transport or API error."""
    import httpx

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{settings.litellm_base_url.rstrip('/')}/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{CONTEXT_PROMPT}\n\nPage:\n{page_text}\n\nExcerpt:\n{chunk}",
                    }
                ],
            },
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()


def _chunk_contexts(
    pages: list[FilePage],
    *,
    model: str,
    max_tokens: int,
    chunk_size: int,
    chunk_overlap: int,
    settings: Any,
) -> dict[int, dict[int, str]]:
    """The context sentence of every chunk, keyed by page index then chunk index.

    One chat call per chunk, so a file costs as many calls as it has chunks. A page
    that fails gives up after its first failed call, and the chunks already placed
    keep their sentence: ``chunk_textual`` stores the plain chunk where no sentence
    arrived, so a model outage degrades the file to Recursive Chunking instead of
    failing it.
    """
    if not model:
        logger.warning("chunk_strategy_context_skipped reason=no_model")
        return {}

    out: dict[int, dict[int, str]] = {}
    for page in pages:
        text = (page.text or "").strip()
        if not text:
            continue
        chunks = chunk_text(text, chunk_size, chunk_overlap, "recursive")
        placed: dict[int, str] = {}
        for index, chunk in enumerate(chunks):
            try:
                placed[index] = _context_sentence(
                    text,
                    chunk,
                    model=model,
                    max_tokens=max_tokens,
                    settings=settings,
                )
            except Exception as exc:
                logger.warning(
                    "chunk_strategy_context_failed page=%d chunk=%d model=%s error=%s",
                    page.page_index,
                    index,
                    model,
                    exc,
                )
                break
        out[page.page_index] = placed
    return out


def _plans_for(
    text: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    config: dict[str, Any] | None,
    similarities: list[float] | None,
    context: dict[int, str] | None,
) -> list[ChunkPlan]:
    """The records one page produces, whichever shape its strategy has.

    Three strategies return records of more than one kind, so they have their own
    function. The rest return one kind and go through ``chunk_text``.
    """
    if strategy == "parent_child":
        return chunk_parent_child(
            text,
            chunk_size,
            chunk_overlap,
            child_size=_setting_int(config, "child_chunk_size", 0),
            child_overlap=_setting_int(config, "child_overlap", 0),
        )
    if strategy == "page_level":
        return chunk_page(text, _setting_int(config, "max_page_chars", 0))
    if strategy == "sentence_window":
        return chunk_sentence_window(text, _setting_int(config, "window_sentences", 2))
    if strategy == "contextual":
        return chunk_textual(text, chunk_size, chunk_overlap, context=context)
    return [
        ChunkPlan(text=chunk)
        for chunk in chunk_text(
            text,
            chunk_size,
            chunk_overlap,
            strategy,
            config=config,
            similarities=similarities,
        )
    ]


def _chunk_pages(
    pages: list[FilePage],
    chunk_size: int,
    chunk_overlap: int,
    strategy: str = DEFAULT_CHUNK_STRATEGY,
    config: dict[str, Any] | None = None,
    similarities: dict[int, list[float]] | None = None,
    contexts: dict[int, dict[int, str]] | None = None,
) -> list[FilePage]:
    """Split every page into chunks, one FilePage per chunk.

    ``page_index`` keeps the source page and ``chunk_index`` counts the records
    inside it. A page whose text is blank yields no chunk, which is what the
    writers did with it before chunking existed.

    ``modality`` and ``image_ref`` carry over, because a figure or a page image is
    a record in its own right and every writer and the store payload need to know
    that.

    ``parent_child`` emits parent records first and child records after them, and
    ``sentence_window`` does the same with window and sentence records. A record's
    ``parent_ref`` of ``<page_index>:<parent_ordinal>`` then resolves to the record
    whose ``chunk_index`` equals the ordinal.
    """
    out: list[FilePage] = []
    for page in pages:
        plans = _plans_for(
            page.text or "",
            strategy,
            chunk_size,
            chunk_overlap,
            config,
            (similarities or {}).get(page.page_index),
            (contexts or {}).get(page.page_index),
        )
        for index, plan in enumerate(plans):
            out.append(
                FilePage(
                    page_index=page.page_index,
                    text=plan.text,
                    image_png=page.image_png if index == 0 else None,
                    chunk_index=index,
                    modality=page.modality,
                    image_ref=page.image_ref,
                    record_type=plan.record_type,
                    parent_ref=(
                        f"{page.page_index}:{plan.parent_ordinal}"
                        if plan.parent_ordinal is not None
                        else None
                    ),
                )
            )
    return out


def _assign_image_chunk_indexes(pages: list[FilePage]) -> list[FilePage]:
    """Give every image record a chunk_index above its page's text chunks.

    Two records that share ``(page_index, chunk_index)`` collide on one Redis key
    and on one store row, so an image record never restarts at zero beside the
    text chunks of the page it belongs to.
    """
    next_index: dict[int, int] = {}
    for page in pages:
        if page.modality != "image":
            next_index[page.page_index] = max(
                next_index.get(page.page_index, 0), page.chunk_index + 1
            )
    out: list[FilePage] = []
    for page in pages:
        if page.modality != "image":
            out.append(page)
            continue
        index = next_index.get(page.page_index, 0)
        next_index[page.page_index] = index + 1
        out.append(replace(page, chunk_index=index))
    return out


def _resolve_modality_mode(product: Any) -> str:
    profile = getattr(product, "ingestion_profile", None)
    if profile is None:
        return DEFAULT_MODALITY_MODE
    mode = profile.modality_mode
    return mode.value if hasattr(mode, "value") else str(mode)


def _resolve_text_embedding_model(product: Any) -> str:
    """The one text embedding model this product uses for every destination."""
    profile = getattr(product, "ingestion_profile", None)
    stored = profile.text_embedding_model if profile else None
    return stored or get_settings().embedding_model


def _resolve_image_embedding_model(product: Any) -> str:
    """The multimodal model a rendered page image is embedded with.

    Falls back to the environment value. The profile API rejects ``text_images``
    without a model, so the fallback only covers a row that reached the database
    without that check.
    """
    profile = getattr(product, "ingestion_profile", None)
    stored = profile.image_embedding_model if profile else None
    return stored or get_settings().multimodal_embedding_model


# Every page image this fanout writes lives under this prefix inside the source
# bucket, so the next listing can tell its own output from source content.
PAGE_IMAGE_PREFIX = "_pages/"


def page_image_object_key(file_key: str, page_index: int) -> str:
    """Where one rendered page image lives inside the source bucket."""
    return f"{PAGE_IMAGE_PREFIX}{file_key}/page-{page_index:05d}.png"


def drop_generated_page_images(remote: dict[str, Any]) -> int:
    """Remove the fanout's own page images from a source listing.

    A page image is output, not input: it has no pages of its own, so a listing
    that fed it back would index a PNG as text on every tick. Dropping the key here
    also lets the delete sweep purge a row for one written before this rule
    existed. Returns the number of keys dropped. Mutates ``remote`` in place.
    """
    keys = [key for key in remote if key.startswith(PAGE_IMAGE_PREFIX)]
    for key in keys:
        remote.pop(key)
    return len(keys)


async def _page_image_records(
    pages: list[FilePage], *, bucket: str, file_key: str
) -> tuple[list[FilePage], list[FilePage]]:
    """Store every page image, and build one record per page.

    Returns the page records and, separately, the pages that rendered no image.
    Every text format lands in the second list, and so does a PDF page PyMuPDF
    cannot rasterise; the caller puts those through the ordinary text path, so no
    content is lost.

    The record keeps the page's extracted text, because a lexical or relational
    store searches text and only the vector stores read the image. ``image_ref``
    names the stored object, which is what a later reader downloads.
    """
    records: list[FilePage] = []
    without_image: list[FilePage] = []
    for page in pages:
        if not page.image_png:
            without_image.append(page)
            continue
        object_key = page_image_object_key(file_key, page.page_index)
        await put_object(bucket, object_key, page.image_png)
        records.append(
            FilePage(
                page_index=page.page_index,
                text=page.text or "",
                # The bytes are in the bucket now, so only the key travels further.
                image_png=page.image_png,
                modality="image",
                record_type="page",
                image_ref={
                    "page_index": page.page_index,
                    "bucket": bucket,
                    "key": object_key,
                },
            )
        )
    return records, without_image


@dataclass
class ChunkRecord:
    """One chunk plus the vector every vector destination reuses."""

    page: FilePage
    dense_vector: list[float] | None = None


def _same_dimension(dimension: int | None, vector: list[float], model: str) -> int:
    """The batch dimension, checked against the vector just returned."""
    if dimension is None:
        return len(vector)
    if len(vector) != dimension:
        raise RuntimeError(
            f"The embedder returned {len(vector)}-dimension vectors after "
            f"{dimension}-dimension ones in the same batch. Model '{model}' "
            "answered part of the batch; the rest fell back to a local model."
        )
    return dimension


def _embed_records(records: list[ChunkRecord], *, model: str, settings: Any) -> None:
    """Fill ``dense_vector`` on every record in place. One embed call per chunk.

    Every vector must have the same length. The client falls back to a local model
    when the proxy call fails, and that model has a different dimension, so a
    partial outage inside one batch would otherwise store a mixed set of vectors.
    A disagreement is an error, not something to store.
    """
    embedder = EmbeddingClient(
        base_url=settings.litellm_base_url,
        api_key=settings.openai_api_key,
        model=model,
    )
    dimension: int | None = None
    for record in records:
        text = (record.page.text or "").strip()
        if not text:
            continue
        vector = embedder.embed_passage(text)
        dimension = _same_dimension(dimension, vector, model)
        record.dense_vector = vector


def _embed_image_records(records: list[ChunkRecord], *, model: str, settings: Any) -> None:
    """Fill ``dense_vector`` from each record's page image. One call per page.

    The page text is not what is embedded here: the vector must describe the page
    as the multimodal model sees it, which is the whole point of the modality. A
    record with no image is skipped, so a page that fell back to the text path is
    embedded by ``_embed_records`` with the text model instead.
    """
    embedder = EmbeddingClient(
        base_url=settings.litellm_base_url,
        api_key=settings.openai_api_key,
        model=model,
    )
    dimension: int | None = None
    for record in records:
        image = record.page.image_png
        if not image:
            continue
        vector = embedder.embed_image_png(image)
        dimension = _same_dimension(dimension, vector, model)
        record.dense_vector = vector


def _is_local_source(s: Any) -> bool:
    if getattr(s, "connector_type", None) == "local_filesystem":
        return True
    if (getattr(s, "config", None) or {}).get("source_type") == "local_filesystem":
        return True
    if getattr(s, "minio_bucket", None) and str(s.minio_bucket).startswith("local-"):
        return True
    return False


async def execute_universal_fanout_sync(
    db: AsyncSession, product: KnowledgeProduct | uuid.UUID | str
) -> dict[str, Any]:
    """Differential CRUD fanout for one Knowledge Product.

    Detect a change from the object's metadata (etag/size), not from its bytes.
    Download and chunk a file only when a destination still needs it.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.shared.db.models import KnowledgeProductSource

    if isinstance(product, (uuid.UUID, str)):
        product_uuid = uuid.UUID(str(product))
        res = await db.execute(
            select(KnowledgeProduct)
            .options(
                selectinload(KnowledgeProduct.sources).selectinload(KnowledgeProductSource.source),
                selectinload(KnowledgeProduct.destinations),
            )
            .where(KnowledgeProduct.id == product_uuid)
        )
        product = res.scalar_one_or_none()
        if not product:
            logger.warning("universal_fanout_product_not_found product_id=%s", product_uuid)
            return {"status": "error", "message": f"Product {product_uuid} not found"}

    logger.info("starting_universal_fanout_sync product_id=%s name=%s", product.id, product.name)

    product_id = product.id
    enabled_destinations = [d for d in (product.destinations or []) if d.enabled]
    # Every destination, enabled or not: a paused store that already holds data
    # for a changed or deleted file must still lose it.
    all_by_type = {d.destination_type: d for d in (product.destinations or [])}
    enabled_types = {d.destination_type for d in enabled_destinations}
    chunk_size, chunk_overlap = _resolve_chunking(product)
    chunk_strategy = _resolve_chunk_strategy(product)
    chunk_config = _resolve_chunk_config(product)
    # The contextual strategy reads these once per chunk, so they are read from the
    # stored config once per tick.
    context_model = str(chunk_config.get("context_model") or "")
    context_max_tokens = min(max(_setting_int(chunk_config, "context_max_tokens", 100), 50), 500)
    linked_sources = [s.source for s in (product.sources or []) if s.source]

    settings = get_settings()
    modality_mode = _resolve_modality_mode(product)
    # A text-with-images product keeps one vector per page, in Qdrant. The
    # multimodal model that made those vectors is the only reader, and the other
    # stores search text, which these records no longer carry as their content.
    if modality_mode == "text_images":
        enabled_types = enabled_types & {"vector_qdrant"}
    embedding_model = _resolve_text_embedding_model(product)
    image_embedding_model = _resolve_image_embedding_model(product)
    # Vector work is per tick, not per destination: Qdrant always needs a vector,
    # and Postgres needs one only when its embedding column is on.
    pg_dest = all_by_type.get("relational_pgvector")
    pg_store_embeddings = bool(((pg_dest.config if pg_dest else {}) or {}).get("store_embeddings", True))
    needs_vectors = "vector_qdrant" in enabled_types or (
        "relational_pgvector" in enabled_types and pg_store_embeddings
    )

    empty = {
        "status": "success",
        "files_processed": 0,
        "files_added": 0,
        "files_updated": 0,
        "files_deleted": 0,
        "files_unchanged": 0,
        "pages_processed": 0,
        "pages_without_image": 0,
        "destinations_synced": [],
    }

    if not linked_sources:
        logger.warning("universal_fanout_no_sources product_id=%s", product_id)
        return {**empty, "message": "No linked MinIO source buckets to sync."}
    if not enabled_types:
        logger.info("universal_fanout_no_enabled_destinations product_id=%s", product_id)
        return {**empty, "message": "No destination is enabled."}

    total_files = 0
    total_added = 0
    total_updated = 0
    total_deleted = 0
    total_unchanged = 0
    total_pages = 0
    total_pages_without_image = 0
    destinations_synced: list[str] = []

    publish(product_id, "tick_start")

    for source in linked_sources:
        bucket_label = source.minio_bucket or str(source.id)
        is_local = _is_local_source(source)

        if is_local:
            from src.shared.storage import storage_root

            folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
            local_dir = storage_root() / "local_sources" / folder_name
            local_dir.mkdir(parents=True, exist_ok=True)

            remote: dict[str, tuple[str, int, Any]] = {}
            for p in local_dir.rglob("*"):
                if p.is_file():
                    key = str(p.relative_to(local_dir)).replace("\\", "/")
                    stat = p.stat()
                    remote[key] = (str(stat.st_mtime), stat.st_size, p)
        else:
            bucket = source.minio_bucket
            try:
                objs = await list_objects(bucket)
            except Exception as exc:
                logger.error("minio_list_objects_failed bucket=%s error=%s", bucket, str(exc))
                continue

            remote = {}
            for obj in objs:
                key = getattr(obj, "key", "")
                if not key or key.endswith("/"):
                    continue
                token = str(getattr(obj, "etag", "") or getattr(obj, "last_modified", "") or "")
                size = int(getattr(obj, "size", 0) or 0)
                remote[key] = (token, size, obj)

        # A `*_scrp.txt` object is a URL list, not content, and its run folder holds page
        # screenshots. Both stay out of the stores whether or not the source switch is on.
        drop_webscrape_control_objects(remote)
        # The page images this fanout wrote for text_images mode live in this same
        # bucket. They are output, not input.
        drop_generated_page_images(remote)

        res = await db.execute(
            select(KnowledgeProductFile).where(
                KnowledgeProductFile.knowledge_product_id == product_id,
                KnowledgeProductFile.source_id == source.id,
            )
        )
        by_key = {rec.file_key: rec for rec in res.scalars().all()}

        # 1. ADD, UPDATE and CATCH-UP
        for key, (token, size, item) in remote.items():
            try:
                row = by_key.get(key)
                changed = row is None or row.etag != token or row.size_bytes != size
                already = set(row.destinations_synced or []) if row is not None else set()
                missing = sorted(enabled_types - already)
                if not changed and not missing:
                    total_unchanged += 1
                    continue

                data = item.read_bytes() if is_local else await get_object(bucket, key)

                if row is None:
                    row = KnowledgeProductFile(
                        knowledge_product_id=product_id,
                        source_id=source.id,
                        file_key=key,
                        status="pending",
                    )
                    db.add(row)
                    by_key[key] = row

                if changed:
                    # A changed file must leave the stores before its new
                    # content lands, otherwise the old page rows survive.
                    for dest_type in sorted(already):
                        await asyncio.to_thread(
                            _PURGERS[dest_type],
                            (all_by_type[dest_type].config or {}) if dest_type in all_by_type else {},
                            str(source.id),
                            key,
                        )
                    row.destinations_synced = []
                    missing = sorted(enabled_types)

                publish(
                    product_id,
                    "file_start",
                    source_id=str(source.id),
                    file_key=key,
                    change="added" if row.status == "pending" and not already else ("updated" if changed else "resynced"),
                )

                suffix = Path(key).suffix or ".bin"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)

                try:
                    source_pages = list(
                        iter_file_pages(
                            tmp_path,
                            mime_type=None,
                            original_name=key,
                            # text_images stores one record per page, so the page
                            # must arrive as an image. Every other mode needs the
                            # text alone.
                            render_pages=modality_mode == "text_images",
                            layout=chunk_strategy in {"section", "layout"},
                        )
                    )
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()

                if not source_pages:
                    logger.warning("fanout_no_pages file=%s", key)
                    row.etag = token
                    row.size_bytes = size
                    row.status = "pending" if missing else "synced"
                    await db.commit()
                    continue

                if modality_mode == "text_images":
                    image_pages, text_pages = await _page_image_records(
                        source_pages, bucket=source.minio_bucket, file_key=key
                    )
                    pages = image_pages
                    if text_pages:
                        # A text format renders no page image, so those pages keep
                        # the text path instead of being dropped.
                        total_pages_without_image += len(text_pages)
                        publish(
                            product_id,
                            "page_image_missing",
                            file_key=key,
                            pages=len(text_pages),
                        )
                        pages += await asyncio.to_thread(
                            _chunk_pages,
                            text_pages,
                            chunk_size,
                            chunk_overlap,
                            chunk_strategy,
                            chunk_config,
                        )
                else:
                    # Two strategies block before chunking, and both run in a
                    # thread so the event loop keeps serving the other files.
                    # context_aware embeds the page's sentences to find topic
                    # shifts; contextual asks a chat model for one sentence per
                    # chunk.
                    similarities = None
                    if chunk_strategy == "context_aware":
                        similarities = await asyncio.to_thread(
                            _context_similarities,
                            source_pages,
                            model=embedding_model,
                            settings=settings,
                        )
                    contexts = None
                    if chunk_strategy == "contextual":
                        contexts = await asyncio.to_thread(
                            _chunk_contexts,
                            source_pages,
                            model=context_model,
                            max_tokens=context_max_tokens,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            settings=settings,
                        )
                    pages = await asyncio.to_thread(
                        _chunk_pages,
                        source_pages,
                        chunk_size,
                        chunk_overlap,
                        chunk_strategy,
                        chunk_config,
                        similarities,
                        contexts,
                    )
                pages = _assign_image_chunk_indexes(pages)
                if not pages:
                    # Every page was blank. Without this the writers get an empty
                    # list, write nothing and still report success, which marks the
                    # destinations synced while the stores hold no documents.
                    logger.warning("fanout_no_chunks file=%s pages=%d", key, len(source_pages))
                    row.etag = token
                    row.size_bytes = size
                    row.pages_indexed = len(source_pages)
                    row.status = "pending" if missing else "synced"
                    await db.commit()
                    continue

                total_files += 1
                total_pages += len(source_pages)
                if changed:
                    if row.id is not None and already:
                        total_updated += 1
                    else:
                        total_added += 1

                row.status = "syncing"
                await db.commit()

                for dest_type in missing:
                    publish(product_id, "destination_start", file_key=key, destination_type=dest_type)

                records = [ChunkRecord(page=page) for page in pages]
                if needs_vectors:
                    # A failure here reaches the per-file handler below, which
                    # leaves destinations_synced untouched so the next tick
                    # retries every destination. No store is half-written.
                    image_records = [r for r in records if r.page.image_png]
                    text_records = [r for r in records if not r.page.image_png]
                    # A text-with-images product embeds the pages that rendered no
                    # image with the multimodal model too: one collection holds one
                    # vector space, so both groups must come from one model.
                    text_model = (
                        image_embedding_model
                        if modality_mode == "text_images"
                        else embedding_model
                    )
                    if image_records:
                        await asyncio.to_thread(
                            _embed_image_records,
                            image_records,
                            model=image_embedding_model,
                            settings=settings,
                        )
                    if text_records:
                        await asyncio.to_thread(
                            _embed_records, text_records, model=text_model, settings=settings
                        )
                    if image_records and text_records and image_embedding_model != text_model:
                        # A collection holds one vector size, and these two groups
                        # come from two models. The reader must hear it from the log
                        # rather than from a dimension error on an unrelated file.
                        logger.warning(
                            "fanout_mixed_vector_models file=%s image_model=%s text_model=%s "
                            "note=one of the two groups will fail to store",
                            key,
                            image_embedding_model,
                            embedding_model,
                        )

                results = await asyncio.gather(
                    *[
                        _fanout_to_destination(
                            dest_type=dest_type,
                            dest_config=all_by_type[dest_type].config or {},
                            source_id=source.id,
                            product_id=product_id,
                            file_key=key,
                            records=records,
                        )
                        for dest_type in missing
                    ],
                    return_exceptions=True,
                )

                synced = list(row.destinations_synced or [])
                error_message = None
                for dest_type, result in zip(missing, results, strict=True):
                    if isinstance(result, Exception):
                        logger.error(
                            "fanout_destination_failed dest=%s file=%s error=%s",
                            dest_type,
                            key,
                            result,
                        )
                        publish(
                            product_id,
                            "destination_failed",
                            file_key=key,
                            destination_type=dest_type,
                            error=str(result),
                        )
                        error_message = str(result)
                        continue
                    if dest_type not in synced:
                        synced.append(dest_type)
                    if dest_type not in destinations_synced:
                        destinations_synced.append(dest_type)
                    publish(
                        product_id,
                        "destination_done",
                        file_key=key,
                        destination_type=dest_type,
                        pages=len(source_pages),
                    )

                row.destinations_synced = synced
                row.etag = token
                row.size_bytes = size
                row.content_hash = hashlib.sha256(data).hexdigest()
                row.pages_indexed = len(source_pages)
                row.error_message = error_message
                row.status = "synced" if set(synced) >= enabled_types else "failed" if error_message else "pending"
                row.last_synced_at = datetime.now(UTC)
                await db.commit()

                if error_message:
                    publish(product_id, "file_failed", source_id=str(source.id), file_key=key, error=error_message)
                else:
                    publish(product_id, "file_synced", source_id=str(source.id), file_key=key, pages=len(source_pages))
            except Exception as exc:
                logger.error(
                    "fanout_file_processing_failed bucket=%s key=%s error=%s",
                    bucket_label,
                    key,
                    str(exc),
                )
                publish(product_id, "file_failed", source_id=str(source.id), file_key=key, error=str(exc))

        # 2. DELETE — objects that left the bucket
        for file_key, rec in by_key.items():
            if file_key in remote:
                continue
            try:
                for dest_type in sorted(set(rec.destinations_synced or [])):
                    await asyncio.to_thread(
                        _PURGERS[dest_type],
                        (all_by_type[dest_type].config or {}) if dest_type in all_by_type else {},
                        str(source.id),
                        file_key,
                    )
                await db.delete(rec)
                await db.commit()
                total_deleted += 1
                publish(product_id, "file_deleted", source_id=str(source.id), file_key=file_key)
                logger.info("universal_fanout_file_deleted product_id=%s file_key=%s", product_id, file_key)
            except Exception as exc:
                logger.error(
                    "universal_fanout_delete_failed product_id=%s file_key=%s error=%s",
                    product_id,
                    file_key,
                    str(exc),
                )

    logger.info(
        "universal_fanout_sync_completed product_id=%s files=%d added=%d updated=%d deleted=%d pages=%d destinations=%s",
        product_id,
        total_files,
        total_added,
        total_updated,
        total_deleted,
        total_pages,
        destinations_synced,
    )

    publish(
        product_id,
        "tick_done",
        files_added=total_added,
        files_updated=total_updated,
        files_deleted=total_deleted,
        files_unchanged=total_unchanged,
        pages=total_pages,
        destinations=destinations_synced,
    )

    return {
        "status": "success",
        "files_processed": total_files,
        "files_added": total_added,
        "files_updated": total_updated,
        "files_deleted": total_deleted,
        "files_unchanged": total_unchanged,
        "pages_processed": total_pages,
        "pages_without_image": total_pages_without_image,
        "destinations_synced": destinations_synced,
    }


async def _fanout_to_destination(
    dest_type: str,
    dest_config: dict[str, Any],
    source_id: uuid.UUID,
    product_id: uuid.UUID,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    """Fan out chunk content and shared vectors to a specific destination engine."""
    await asyncio.to_thread(
        _sync_fanout_to_destination,
        dest_type,
        dest_config,
        str(source_id),
        str(product_id),
        file_key,
        records,
    )


async def purge_knowledge_product(db: AsyncSession, product: KnowledgeProduct) -> dict[str, Any]:
    """Purge every indexed artifact of a product, then its ledger rows."""
    from sqlalchemy import select

    res = await db.execute(
        select(KnowledgeProductFile).where(KnowledgeProductFile.knowledge_product_id == product.id)
    )
    records = list(res.scalars().all())
    purged_files = 0

    for rec in records:
        if rec.file_key:
            await purge_file_from_destinations(
                product,
                str(rec.source_id),
                rec.file_key,
                destination_types=list(rec.destinations_synced or []) or None,
            )
            purged_files += 1
        await db.delete(rec)

    await db.commit()
    return {
        "purged_files": purged_files,
        "source_ids": [str(link.source_id) for link in (product.sources or [])],
        "destinations": [d.destination_type for d in (product.destinations or []) if d.enabled],
    }


async def purge_file_from_destinations(
    product: KnowledgeProduct,
    source_id: str,
    file_key: str,
    destination_types: list[str] | None = None,
) -> None:
    """Purge one file's artifacts from the given destinations.

    ``destination_types`` defaults to every enabled destination. Pass an explicit
    list to also purge stores that are currently paused but still hold the file.
    """
    all_by_type = {d.destination_type: d for d in (product.destinations or [])}
    if destination_types is None:
        targets = sorted(all_by_type)
        targets = [t for t in targets if all_by_type[t].enabled]
    else:
        targets = sorted(set(destination_types))

    for dest_type in targets:
        dest = all_by_type.get(dest_type)
        dest_config = (dest.config or {}) if dest else {}
        try:
            await asyncio.to_thread(_PURGERS[dest_type], dest_config, source_id, file_key)
        except Exception as exc:
            logger.error("purge_file_from_destination_failed dest=%s file=%s error=%s", dest_type, file_key, exc)


def _purge_qdrant(dest_config: dict[str, Any], source_id: str, file_key: str) -> None:
    settings = get_settings()
    collection_name = dest_config.get("collection_name", "knowledge_qdrant_collection")
    # Must match `_write_qdrant`, or a purge deletes from a store nothing wrote to.
    url = settings.qdrant_kp_url or settings.qdrant_url
    api_key = settings.qdrant_api_key
    try:
        from qdrant_client import QdrantClient, models

        client = QdrantClient(url=url, api_key=api_key, timeout=5.0)
        client.delete(
            collection_name=collection_name,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(key="file_key", match=models.MatchValue(value=file_key)),
                    models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id)),
                ]
            ),
        )
        logger.info("qdrant_points_deleted collection=%s file_key=%s", collection_name, file_key)
    except Exception as exc:
        logger.warning("qdrant_purge_failed file_key=%s error=%s", file_key, exc)


def _purge_opensearch(dest_config: dict[str, Any], source_id: str, file_key: str) -> None:
    settings = get_settings()
    index_name = dest_config.get("index_name", "knowledge_lexical_index")
    url = _resolve_opensearch_url(dest_config, settings)
    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            # source_id must use the .keyword subfield: the field is mapped as
            # text, so a term query against it would match no analysed token.
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"file_key.keyword": file_key}},
                                        {"match_phrase": {"file_key": file_key}},
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                            {"term": {"source_id.keyword": source_id}},
                        ]
                    }
                }
            }
            resp = client.post(f"{url}/{index_name}/_delete_by_query", json=query)
        logger.info(
            "opensearch_docs_deleted index=%s file_key=%s status=%s",
            index_name,
            file_key,
            resp.status_code,
        )
    except Exception as exc:
        logger.warning("opensearch_purge_failed file_key=%s error=%s", file_key, exc)


def _purge_redis(dest_config: dict[str, Any], source_id: str, file_key: str) -> None:
    settings = get_settings()
    url = settings.redis_url
    prefix = _redis_prefix(dest_config)
    try:
        import redis

        r = redis.Redis.from_url(url)
        pattern = f"{_redis_glob_escape(prefix)}:{_redis_glob_escape(source_id)}:{_redis_glob_escape(file_key)}*"
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
        logger.info("redis_keys_deleted count=%d file_key=%s", len(keys), file_key)
    except Exception as exc:
        logger.warning("redis_purge_failed file_key=%s error=%s", file_key, exc)


def _purge_postgres(dest_config: dict[str, Any], source_id: str, file_key: str) -> None:
    settings = get_settings()
    table_name = _qualified_pg_table(dest_config)
    schema = _pg_schema(dest_config)
    try:
        conn = connect_pg(dest_config, settings)
        if conn:
            with conn:
                with conn.cursor() as cur:
                    if schema != "public":
                        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                    cur.execute(
                        f"DELETE FROM {table_name} WHERE file_key = %s AND source_id = %s",
                        (file_key, source_id),
                    )
            logger.info("postgres_rows_deleted table=%s file_key=%s", table_name, file_key)
    except Exception as exc:
        logger.warning("postgres_purge_failed file_key=%s error=%s", file_key, exc)


def _write_qdrant(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    settings = get_settings()
    collection_name = dest_config.get("collection_name", "knowledge_qdrant_collection")
    # The `kp_*` collections live on the knowledge-product Qdrant, which is a
    # different instance from the scraper's `scrape_embeddings` store.
    url = settings.qdrant_kp_url or settings.qdrant_url
    api_key = settings.qdrant_api_key

    points = []
    for record in records:
        # A page image is a record in its own right, and a scanned page has no text
        # layer at all. Its texture is the whole point of the page-image mode, so
        # the text rule that drops an empty chunk must not drop it.
        if not (record.page.text or "").strip() and not record.page.image_png:
            continue
        if record.dense_vector is None:
            # Vector work is skipped only when no enabled destination needs a
            # vector, and then this writer is not called.
            continue
        payload = _build_fanout_payload(
            source_id=uuid.UUID(source_id),
            product_id=uuid.UUID(product_id),
            file_key=file_key,
            page=record.page,
        )
        points.append({
            "point_id": str(uuid.uuid4()),
            "dense_vector": record.dense_vector,
            "payload": payload,
        })

    if not points:
        return

    qdrant = QdrantVectorStore(url=url, collection=collection_name, api_key=api_key)
    # The dimension comes from the model output, so a model change can never
    # disagree with the collection.
    vector_size = len(points[0]["dense_vector"])
    qdrant.ensure_collection(
        vector_size=vector_size,
        enable_sparse=False,
        hnsw_m=int(dest_config.get("hnsw_m") or 16),
        hnsw_ef_construct=int(dest_config.get("hnsw_ef_construct") or 100),
        # Recreating here would delete every point the product already has.
        # apply-profile purges a store before a deliberate model change, so a
        # mismatch at this point means the embedder changed under us.
        recreate_on_mismatch=False,
    )
    # A request carries a few points at a time. A page-image record holds its page
    # PNG, so a 23-page scan is about 11 MB in one call: enough for a client
    # timeout, and the retry then blocks the caller for minutes.
    for start in range(0, len(points), 4):
        qdrant.upsert_batch(points[start : start + 4])
    logger.info(
        "qdrant_fanout_complete collection=%s points_count=%d vector_size=%d",
        collection_name,
        len(points),
        vector_size,
    )


def _write_opensearch(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    settings = get_settings()
    index_name = dest_config.get("index_name", "knowledge_lexical_index")
    url = _resolve_opensearch_url(dest_config, settings)
    auth = _opensearch_auth(dest_config)
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            index_settings = {
                "settings": {
                    "index": {
                        "number_of_shards": dest_config.get("number_of_shards", 1),
                        "number_of_replicas": dest_config.get("number_of_replicas", 0),
                        "refresh_interval": dest_config.get("refresh_interval", "1s"),
                    }
                }
            }
            client.put(f"{url}/{index_name}", json=index_settings, auth=auth)
            for record in records:
                page = record.page
                text = page.text or ""
                if not text.strip():
                    continue
                payload = _build_fanout_payload(
                    source_id=uuid.UUID(source_id),
                    product_id=uuid.UUID(product_id),
                    file_key=file_key,
                    page=page,
                )
                doc = {
                    "file_key": file_key,
                    "page_index": page.page_index,
                    "chunk_index": page.chunk_index,
                    "modality": page.modality,
                    "image_ref": page.image_ref,
                    "record_type": payload["record_type"],
                    "parent_ref": payload["parent_ref"],
                    "content": payload["content"],
                    "text": payload["content"],
                    "source_id": payload["source_id"],
                    "source_locator": payload["source_locator"],
                    "created_at": payload["created_at"],
                    "sparse_model": dest_config.get("sparse_model"),
                    "bm25_k1": dest_config.get("bm25_k1"),
                    "bm25_b": dest_config.get("bm25_b"),
                }
                client.post(f"{url}/{index_name}/_doc", json=doc, auth=auth)
        logger.info(
            "opensearch_lexical_indexed index=%s file=%s docs=%d", index_name, file_key, len(records)
        )
    except Exception as exc:
        # Re-raise: the fanout records a per-destination failure from it.
        logger.warning("opensearch_indexing_failed index=%s file=%s error=%s", index_name, file_key, exc)
        raise


def _write_postgres(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    settings = get_settings()
    table_name = _qualified_pg_table(dest_config)
    schema = _pg_schema(dest_config)
    store_embeddings = bool(dest_config.get("store_embeddings", True))
    vector_dim = next((len(r.dense_vector) for r in records if r.dense_vector), 0)
    try:
        conn = connect_pg(dest_config, settings)
        if not conn:
            raise RuntimeError("Could not connect to PostgreSQL with the configured or default credentials")
        with conn:
            with conn.cursor() as cur:
                if schema != "public":
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                if store_embeddings:
                    # The vector column type comes from this extension.
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                if store_embeddings:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id SERIAL PRIMARY KEY,
                            file_key TEXT NOT NULL,
                            source_id TEXT,
                            page_index INT NOT NULL,
                            chunk_index INT NOT NULL DEFAULT 0,
                            modality TEXT NOT NULL DEFAULT 'text',
                            record_type TEXT NOT NULL DEFAULT 'chunk',
                            parent_ref TEXT,
                            content TEXT,
                            embedding vector({vector_dim}),
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                    """)
                else:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id SERIAL PRIMARY KEY,
                            file_key TEXT NOT NULL,
                            source_id TEXT,
                            page_index INT NOT NULL,
                            chunk_index INT NOT NULL DEFAULT 0,
                            modality TEXT NOT NULL DEFAULT 'text',
                            record_type TEXT NOT NULL DEFAULT 'chunk',
                            parent_ref TEXT,
                            content TEXT,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                    """)
                # A table created by an older version has no source_id, no
                # chunk_index and no modality.
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS source_id TEXT")
                cur.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS chunk_index INT NOT NULL DEFAULT 0"
                )
                cur.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS modality TEXT NOT NULL DEFAULT 'text'"
                )
                # record_type and parent_ref came with the parent_child strategy.
                cur.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS record_type TEXT NOT NULL DEFAULT 'chunk'"
                )
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS parent_ref TEXT")
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS ix_{_resolve_pg_table(dest_config)}_source_file "
                    f"ON {table_name} (source_id, file_key)"
                )
                if store_embeddings and vector_dim:
                    if vector_dim <= 2000:
                        # The index the removed algorithm and operator fields used
                        # to describe. Cosine is the only metric the shared
                        # embedder is normalised for.
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS ix_{_resolve_pg_table(dest_config)}_embedding "
                            f"ON {table_name} USING hnsw (embedding vector_cosine_ops)"
                        )
                    else:
                        # pgvector caps an hnsw index at 2000 dimensions for the
                        # vector type. Above it the column is still correct and a
                        # search is an exact scan, only slower.
                        logger.warning(
                            "pgvector_hnsw_skipped table=%s dimensions=%d limit=2000",
                            table_name,
                            vector_dim,
                        )
                for record in records:
                    page = record.page
                    text = page.text or ""
                    if not text.strip():
                        continue
                    if store_embeddings and record.dense_vector is not None:
                        cur.execute(
                            f"INSERT INTO {table_name} (file_key, source_id, page_index, chunk_index, modality, record_type, parent_ref, content, embedding) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                file_key,
                                source_id,
                                page.page_index,
                                page.chunk_index,
                                page.modality,
                                page.record_type,
                                page.parent_ref,
                                text,
                                record.dense_vector,
                            ),
                        )
                    else:
                        cur.execute(
                            f"INSERT INTO {table_name} (file_key, source_id, page_index, chunk_index, modality, record_type, parent_ref, content) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                file_key,
                                source_id,
                                page.page_index,
                                page.chunk_index,
                                page.modality,
                                page.record_type,
                                page.parent_ref,
                                text,
                            ),
                        )
        logger.info(
            "pgvector_relational_upserted table=%s file=%s docs=%d", table_name, file_key, len(records)
        )
    except Exception as exc:
        logger.warning("pgvector_failed file=%s error=%s", file_key, exc)
        raise


def _write_redis(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    settings = get_settings()
    index_prefix = _redis_prefix(dest_config)
    ttl_seconds = int(dest_config.get("ttl_seconds") or 86400)
    parent_child_mapping = bool(dest_config.get("parent_child_mapping", True))
    base = f"{index_prefix}:{source_id}:{file_key}"
    try:
        import json

        import redis

        redis_url = settings.redis_url
        r = redis.from_url(redis_url)
        for record in records:
            page = record.page
            text = page.text or ""
            if not text.strip():
                continue
            key = f"{base}:{page.page_index}:{page.chunk_index}"
            payload = {
                "content": text,
                "file_key": file_key,
                "source_id": source_id,
                "page_index": page.page_index,
                "chunk_index": page.chunk_index,
                "modality": page.modality,
                "image_ref": page.image_ref,
                "record_type": page.record_type,
                "parent_ref": page.parent_ref,
                "similarity_threshold": dest_config.get("similarity_threshold"),
                "embedding_model": settings.embedding_model,
            }
            if parent_child_mapping:
                payload["parent_key"] = base
            r.set(key, json.dumps(payload), ex=ttl_seconds)
            if parent_child_mapping:
                r.sadd(f"{base}:children", key)
        if dest_config.get("raptor_summaries"):
            summary_model = dest_config.get("summary_model") or settings.summary_model
            combined = "\n".join(
                (record.page.text or "")[:500]
                for record in records
                if (record.page.text or "").strip()
            )
            if combined.strip():
                import httpx

                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{settings.litellm_base_url.rstrip('/')}/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                        json={
                            "model": summary_model,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": f"Summarize this document in 3 bullet points:\n{combined[:6000]}",
                                }
                            ],
                            "temperature": 0.2,
                        },
                    )
                    response.raise_for_status()
                    summary = response.json()["choices"][0]["message"]["content"]
                    r.set(f"{base}:summary", summary, ex=ttl_seconds)
        logger.info("redisvl_semantic_cached prefix=%s file=%s docs=%d", index_prefix, file_key, len(records))
    except Exception as exc:
        logger.warning("redisvl_failed file=%s error=%s", file_key, exc)
        raise


_WRITERS: dict[str, Callable[[dict[str, Any], str, str, str, list[ChunkRecord]], None]] = {
    "vector_qdrant": _write_qdrant,
    "lexical_opensearch": _write_opensearch,
    "elasticsearch": _write_opensearch,
    "relational_pgvector": _write_postgres,
    "database_pgvector": _write_postgres,
    "cache_redisvl": _write_redis,
    "cache_redis": _write_redis,
}

_PURGERS: dict[str, Callable[[dict[str, Any], str, str], None]] = {
    "vector_qdrant": _purge_qdrant,
    "lexical_opensearch": _purge_opensearch,
    "elasticsearch": _purge_opensearch,
    "relational_pgvector": _purge_postgres,
    "database_pgvector": _purge_postgres,
    "cache_redisvl": _purge_redis,
    "cache_redis": _purge_redis,
}


def _sync_fanout_to_destination(
    dest_type: str,
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    records: list[ChunkRecord],
) -> None:
    writer = _WRITERS.get(dest_type)
    if writer is None:
        logger.warning("fanout_destination_unsupported type=%s file=%s", dest_type, file_key)
        return
    logger.info("fanning_out_to_destination type=%s file=%s docs=%d", dest_type, file_key, len(records))
    writer(dest_config, source_id, product_id, file_key, records)
