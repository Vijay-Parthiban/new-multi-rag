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
import hashlib
import logging
import re
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion_service.core.knowledge_events import publish
from src.ingestion_service.core.page_yielder import FilePage, iter_file_pages
from src.ingestion_service.embeddings.client import EmbeddingClient
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore
from src.shared.config.settings import get_settings
from src.shared.db.models import KnowledgeProduct, KnowledgeProductFile
from src.shared.storage.s3_client import get_object, list_objects

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _resolve_opensearch_url(dest_config: dict[str, Any], settings: Any) -> str:
    return (
        dest_config.get("endpoint_url")
        or dest_config.get("url")
        or settings.opensearch_url
    ).rstrip("/")


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
    """Candidate Postgres URLs for a destination, best first.

    The configured URL wins. The ingestion database is next, which is right for
    a Postgres-backed deployment. Non-Postgres URLs are dropped: the dev default
    is SQLite, and psycopg cannot open it.
    """
    candidates = [
        _normalize_pg_url(dest_config.get("connection_url")),
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


def _resolve_litellm(dest_config: dict[str, Any], settings: Any) -> tuple[str, str]:
    base_url = dest_config.get("litellm_base_url") or settings.litellm_base_url
    api_key = dest_config.get("litellm_api_key") or settings.openai_api_key
    return base_url, api_key


def _resolve_embedding_model(dest_config: dict[str, Any], settings: Any) -> str:
    return dest_config.get("embedding_model") or settings.embedding_model


def _qualified_pg_table(dest_config: dict[str, Any]) -> str:
    table_name = _resolve_pg_table(dest_config)
    schema = _pg_schema(dest_config)
    if schema != "public":
        return f"{schema}.{table_name}"
    return table_name


def _opensearch_auth(dest_config: dict[str, Any]) -> tuple[str, str] | None:
    auth_type = (dest_config.get("auth_type") or "none").lower()
    if auth_type == "basic":
        username = dest_config.get("username") or ""
        password = dest_config.get("password") or ""
        if username:
            return username, password
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
    content = (page.text or "").strip()
    return {
        "source_type": FILE_INGEST_SOURCE_TYPE,
        "source_id": str(source_id),
        "source_locator": file_key,
        "file_key": file_key,
        "file_name": file_name,
        "original_name": file_name,
        "title": file_name,
        "page_index": page.page_index,
        "chunk_index": page.page_index,
        "type": "text",
        "content": content,
        "text": content,
        "knowledge_product_id": str(product_id),
        "created_at": datetime.now(UTC).isoformat(),
    }


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
    linked_sources = [s.source for s in (product.sources or []) if s.source]

    empty = {
        "status": "success",
        "files_processed": 0,
        "files_added": 0,
        "files_updated": 0,
        "files_deleted": 0,
        "files_unchanged": 0,
        "pages_processed": 0,
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
                    pages = list(iter_file_pages(tmp_path, mime_type=None, original_name=key))
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()

                if not pages:
                    logger.warning("fanout_no_pages file=%s", key)
                    row.etag = token
                    row.size_bytes = size
                    row.status = "pending" if missing else "synced"
                    await db.commit()
                    continue

                total_files += 1
                total_pages += len(pages)
                if changed:
                    if row.id is not None and already:
                        total_updated += 1
                    else:
                        total_added += 1

                row.status = "syncing"
                await db.commit()

                for dest_type in missing:
                    publish(product_id, "destination_start", file_key=key, destination_type=dest_type)

                results = await asyncio.gather(
                    *[
                        _fanout_to_destination(
                            dest_type=dest_type,
                            dest_config=all_by_type[dest_type].config or {},
                            source_id=source.id,
                            product_id=product_id,
                            file_key=key,
                            pages=pages,
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
                        pages=len(pages),
                    )

                row.destinations_synced = synced
                row.etag = token
                row.size_bytes = size
                row.content_hash = hashlib.sha256(data).hexdigest()
                row.pages_indexed = len(pages)
                row.error_message = error_message
                row.status = "synced" if set(synced) >= enabled_types else "failed" if error_message else "pending"
                row.last_synced_at = datetime.now(UTC)
                await db.commit()

                if error_message:
                    publish(product_id, "file_failed", source_id=str(source.id), file_key=key, error=error_message)
                else:
                    publish(product_id, "file_synced", source_id=str(source.id), file_key=key, pages=len(pages))
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
        "destinations_synced": destinations_synced,
    }


async def _fanout_to_destination(
    dest_type: str,
    dest_config: dict[str, Any],
    source_id: uuid.UUID,
    product_id: uuid.UUID,
    file_key: str,
    pages: list[FilePage],
) -> None:
    """Fan out page content and embeddings to a specific destination engine."""
    await asyncio.to_thread(
        _sync_fanout_to_destination,
        dest_type,
        dest_config,
        str(source_id),
        str(product_id),
        file_key,
        pages,
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
    url = dest_config.get("url") or settings.qdrant_url
    api_key = dest_config.get("api_key") or settings.qdrant_api_key
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
    url = dest_config.get("redis_url") or dest_config.get("url") or settings.redis_url
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
    pages: list[FilePage],
) -> None:
    settings = get_settings()
    collection_name = dest_config.get("collection_name", "knowledge_qdrant_collection")
    url = dest_config.get("url") or settings.qdrant_url
    api_key = dest_config.get("api_key") or settings.qdrant_api_key
    litellm_base_url, litellm_api_key = _resolve_litellm(dest_config, settings)
    embedding_model = _resolve_embedding_model(dest_config, settings)

    embedder = EmbeddingClient(
        base_url=litellm_base_url,
        api_key=litellm_api_key,
        model=embedding_model,
    )

    points = []
    for p in pages:
        text = p.text or ""
        if not text.strip():
            continue
        emb = embedder.embed_passage(text)
        payload = _build_fanout_payload(
            source_id=uuid.UUID(source_id),
            product_id=uuid.UUID(product_id),
            file_key=file_key,
            page=p,
        )
        points.append({
            "point_id": str(uuid.uuid4()),
            "dense_vector": emb,
            "payload": payload,
        })

    if not points:
        return

    qdrant = QdrantVectorStore(url=url, collection=collection_name, api_key=api_key)
    configured_size = dest_config.get("vector_size")
    vector_size = int(configured_size) if configured_size else len(points[0]["dense_vector"])
    qdrant.ensure_collection(vector_size=vector_size, enable_sparse=False)
    qdrant.upsert_batch(points)
    logger.info(
        "qdrant_fanout_complete collection=%s model=%s points_count=%d",
        collection_name,
        embedding_model,
        len(points),
    )


def _write_opensearch(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    pages: list[FilePage],
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
            for p in pages:
                text = p.text or ""
                if not text.strip():
                    continue
                payload = _build_fanout_payload(
                    source_id=uuid.UUID(source_id),
                    product_id=uuid.UUID(product_id),
                    file_key=file_key,
                    page=p,
                )
                doc = {
                    "file_key": file_key,
                    "page_index": p.page_index,
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
        logger.info("opensearch_lexical_indexed index=%s file=%s pages=%d", index_name, file_key, len(pages))
    except Exception as exc:
        # Re-raise: the fanout records a per-destination failure from it.
        logger.warning("opensearch_indexing_failed index=%s file=%s error=%s", index_name, file_key, exc)
        raise


def _write_postgres(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    pages: list[FilePage],
) -> None:
    settings = get_settings()
    table_name = _qualified_pg_table(dest_config)
    schema = _pg_schema(dest_config)
    store_embeddings = bool(dest_config.get("store_embeddings", True))
    litellm_base_url, litellm_api_key = _resolve_litellm(dest_config, settings)
    embedding_model = _resolve_embedding_model(dest_config, settings)
    embedder = None
    if store_embeddings:
        embedder = EmbeddingClient(
            base_url=litellm_base_url,
            api_key=litellm_api_key,
            model=embedding_model,
        )
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
                            content TEXT,
                            embedding vector({int(dest_config.get("vector_size") or 2048)}),
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
                            content TEXT,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                    """)
                # A table created by an older version has no source_id.
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS source_id TEXT")
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS ix_{_resolve_pg_table(dest_config)}_source_file "
                    f"ON {table_name} (source_id, file_key)"
                )
                for p in pages:
                    text = p.text or ""
                    if not text.strip():
                        continue
                    if store_embeddings and embedder is not None:
                        embedding = embedder.embed_passage(text)
                        cur.execute(
                            f"INSERT INTO {table_name} (file_key, source_id, page_index, content, embedding) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (file_key, source_id, p.page_index, text, embedding),
                        )
                    else:
                        cur.execute(
                            f"INSERT INTO {table_name} (file_key, source_id, page_index, content) "
                            "VALUES (%s, %s, %s, %s)",
                            (file_key, source_id, p.page_index, text),
                        )
        logger.info("pgvector_relational_upserted table=%s file=%s pages=%d", table_name, file_key, len(pages))
    except Exception as exc:
        logger.warning("pgvector_failed file=%s error=%s", file_key, exc)
        raise


def _write_redis(
    dest_config: dict[str, Any],
    source_id: str,
    product_id: str,
    file_key: str,
    pages: list[FilePage],
) -> None:
    settings = get_settings()
    index_prefix = _redis_prefix(dest_config)
    ttl_seconds = int(dest_config.get("ttl_seconds") or 86400)
    parent_child_mapping = bool(dest_config.get("parent_child_mapping", True))
    base = f"{index_prefix}:{source_id}:{file_key}"
    try:
        import json

        import redis

        redis_url = dest_config.get("redis_url") or settings.redis_url
        r = redis.from_url(redis_url)
        for p in pages:
            text = p.text or ""
            if not text.strip():
                continue
            key = f"{base}:{p.page_index}"
            payload = {
                "content": text,
                "file_key": file_key,
                "source_id": source_id,
                "page_index": p.page_index,
                "similarity_threshold": dest_config.get("similarity_threshold"),
                "embedding_model": dest_config.get("embedding_model"),
            }
            if parent_child_mapping:
                payload["parent_key"] = base
            r.set(key, json.dumps(payload), ex=ttl_seconds)
            if parent_child_mapping:
                r.sadd(f"{base}:children", key)
        if dest_config.get("raptor_summaries"):
            summary_model = dest_config.get("summary_model") or "gpt-4o-mini"
            litellm_base_url, litellm_api_key = _resolve_litellm(dest_config, settings)
            combined = "\n".join((page.text or "")[:500] for page in pages if (page.text or "").strip())
            if combined.strip():
                import httpx

                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{litellm_base_url.rstrip('/')}/v1/chat/completions",
                        headers={"Authorization": f"Bearer {litellm_api_key}"},
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
        logger.info("redisvl_semantic_cached prefix=%s file=%s pages=%d", index_prefix, file_key, len(pages))
    except Exception as exc:
        logger.warning("redisvl_failed file=%s error=%s", file_key, exc)
        raise


_WRITERS: dict[str, Callable[[dict[str, Any], str, str, str, list[FilePage]], None]] = {
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
    pages: list[FilePage],
) -> None:
    writer = _WRITERS.get(dest_type)
    if writer is None:
        logger.warning("fanout_destination_unsupported type=%s file=%s", dest_type, file_key)
        return
    logger.info("fanning_out_to_destination type=%s file=%s pages=%d", dest_type, file_key, len(pages))
    writer(dest_config, source_id, product_id, file_key, pages)
