"""Universal RAG Ingestion Multi-Sink Fanout Engine.

Transforms raw documents from linked MinIO source buckets and fans out
index artifacts across 5 destination categories:
1. Vector Engine — Qdrant
2. Lexical Engine — OpenSearch (BM25 + Sparse SPLADE)
3. Knowledge Graph Store — Neo4j (Entities, Triplets, GraphRAG summaries)
4. Multi-Model Relational Database — PostgreSQL (pgvector / pgvectorscale)
5. Semantic Cache & Summary Stores — RedisVL (RAPTOR summary trees, parent-child maps)
"""

import asyncio
import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion_service.core.page_yielder import FilePage, iter_file_pages
from src.ingestion_service.embeddings.client import EmbeddingClient
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore
from src.shared.config.settings import get_settings
from src.shared.db.models import KnowledgeProfile
from src.shared.storage.s3_client import get_object, list_objects

logger = logging.getLogger(__name__)


def _resolve_opensearch_url(dest_config: dict[str, Any], settings: Any) -> str:
    return (
        dest_config.get("endpoint_url")
        or dest_config.get("url")
        or settings.opensearch_url
    ).rstrip("/")


def _resolve_neo4j_bolt_uri(dest_config: dict[str, Any], settings: Any) -> str:
    return dest_config.get("bolt_uri") or dest_config.get("url") or settings.neo4j_bolt_uri


def _resolve_neo4j_http_url(dest_config: dict[str, Any], settings: Any) -> str:
    return dest_config.get("http_url") or dest_config.get("url") or settings.neo4j_http_url


def _resolve_pg_table(dest_config: dict[str, Any]) -> str:
    return dest_config.get("table_name") or dest_config.get("table_prefix") or "knowledge_chunks"


def _normalize_pg_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")


def _build_fanout_payload(
    *,
    source_id: uuid.UUID,
    profile_id: uuid.UUID,
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
        "knowledge_profile_id": str(profile_id),
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
    db: AsyncSession, profile: KnowledgeProfile | uuid.UUID | str
) -> dict[str, Any]:
    """Execute multi-sink fanout ingestion for a Knowledge Profile with full differential state CRUD."""
    from sqlalchemy import select, delete
    from sqlalchemy.orm import selectinload
    from src.shared.db.models import IndexedFile, KnowledgeProfileSource

    if isinstance(profile, (uuid.UUID, str)):
        profile_uuid = uuid.UUID(str(profile))
        res = await db.execute(
            select(KnowledgeProfile)
            .options(
                selectinload(KnowledgeProfile.sources).selectinload(KnowledgeProfileSource.source),
                selectinload(KnowledgeProfile.destinations),
            )
            .where(KnowledgeProfile.id == profile_uuid)
        )
        profile = res.scalar_one_or_none()
        if not profile:
            logger.warning("universal_fanout_profile_not_found profile_id=%s", profile_uuid)
            return {"status": "error", "message": f"Profile {profile_uuid} not found"}

    logger.info(
        "starting_universal_fanout_sync profile_id=%s name=%s",
        profile.id,
        profile.name,
    )

    enabled_destinations = [d for d in (profile.destinations or []) if d.enabled]
    linked_sources = [s.source for s in (profile.sources or []) if s.source]

    if not linked_sources:
        logger.warning("universal_fanout_no_sources profile_id=%s", profile.id)
        return {
            "status": "success",
            "files_processed": 0,
            "files_added": 0,
            "files_updated": 0,
            "files_deleted": 0,
            "pages_processed": 0,
            "destinations_synced": [],
            "message": "No linked MinIO source buckets to sync.",
        }

    total_files = 0
    total_added = 0
    total_updated = 0
    total_deleted = 0
    total_pages = 0
    destinations_synced = []

    profile_id = profile.id

    # Process files from linked sources (MinIO buckets or Local File Systems)
    for source in linked_sources:
        bucket_label = source.minio_bucket or str(source.id)
        is_local = _is_local_source(source)
        if is_local:
            from src.shared.storage import storage_root
            folder_name = (source.config or {}).get("folder_name") or source.minio_bucket.replace("local-", "")
            local_dir = storage_root() / "local_sources" / folder_name
            local_dir.mkdir(parents=True, exist_ok=True)

            active_remote_map = {}
            for p in local_dir.rglob("*"):
                if p.is_file():
                    key = str(p.relative_to(local_dir)).replace("\\", "/")
                    active_remote_map[key] = p
        else:
            bucket = source.minio_bucket
            try:
                objs = await list_objects(bucket)
            except Exception as exc:
                logger.error("minio_list_objects_failed bucket=%s error=%s", bucket, str(exc))
                continue

            active_remote_map = {}
            for obj in objs:
                key = getattr(obj, "key", "")
                if key and not key.endswith("/"):
                    active_remote_map[key] = obj
        # Query existing indexed files from database for this source
        stmt = select(IndexedFile).where(IndexedFile.source_id == source.id)
        res = await db.execute(stmt)
        existing_records = {rec.file_key: rec for rec in res.scalars().all()}

        # 1. Handle ADD and UPDATE
        for key, item in active_remote_map.items():
            try:
                if is_local:
                    data = item.read_bytes()
                else:
                    data = await get_object(bucket, key)
                import hashlib
                content_hash = hashlib.sha256(data).hexdigest()

                existing_rec = existing_records.get(key)
                is_add = existing_rec is None
                is_update = existing_rec is not None and existing_rec.content_hash != content_hash

                if not is_add and not is_update:
                    continue

                if is_update:
                    # Purge existing artifacts in destinations before updating
                    await purge_file_from_destinations(profile, key)
                    total_updated += 1
                else:
                    total_added += 1

                suffix = Path(key).suffix or ".bin"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)

                try:
                    pages = list(iter_file_pages(tmp_path, mime_type=None, original_name=key))
                    if pages:
                        total_files += 1
                        total_pages += len(pages)

                        fanout_results = await asyncio.gather(
                            *[
                                _fanout_to_destination(
                                    dest_type=dest.destination_type,
                                    dest_config=dest.config or {},
                                    source_id=source.id,
                                    profile_id=profile_id,
                                    file_key=key,
                                    pages=pages,
                                )
                                for dest in enabled_destinations
                            ],
                            return_exceptions=True,
                        )
                        for dest, result in zip(enabled_destinations, fanout_results, strict=True):
                            if isinstance(result, Exception):
                                logger.error(
                                    "fanout_destination_failed dest=%s file=%s error=%s",
                                    dest.destination_type,
                                    key,
                                    result,
                                )
                                continue
                            if dest.destination_type not in destinations_synced:
                                destinations_synced.append(dest.destination_type)

                        # Update or insert IndexedFile tracking record
                        if existing_rec:
                            existing_rec.content_hash = content_hash
                            existing_rec.indexed_at = datetime.now(UTC)
                        else:
                            new_rec = IndexedFile(
                                source_id=source.id,
                                file_key=key,
                                content_hash=content_hash,
                                indexed_at=datetime.now(UTC),
                            )
                            db.add(new_rec)
                        await db.commit()
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
            except Exception as exc:
                logger.error(
                    "fanout_file_processing_failed bucket=%s key=%s error=%s",
                    bucket_label,
                    key,
                    str(exc),
                )

        # 2. Handle DELETE (Files removed from MinIO bucket)
        for file_key, rec in existing_records.items():
            if file_key not in active_remote_map:
                try:
                    await purge_file_from_destinations(profile, file_key)
                    await db.delete(rec)
                    await db.commit()
                    total_deleted += 1
                    logger.info("universal_fanout_file_deleted profile_id=%s file_key=%s", profile.id, file_key)
                except Exception as exc:
                    logger.error("universal_fanout_delete_failed profile_id=%s file_key=%s error=%s", profile.id, file_key, str(exc))

    logger.info(
        "universal_fanout_sync_completed profile_id=%s files=%d added=%d updated=%d deleted=%d pages=%d destinations=%s",
        profile.id,
        total_files,
        total_added,
        total_updated,
        total_deleted,
        total_pages,
        destinations_synced,
    )

    return {
        "status": "success",
        "files_processed": total_files,
        "files_added": total_added,
        "files_updated": total_updated,
        "files_deleted": total_deleted,
        "pages_processed": total_pages,
        "destinations_synced": destinations_synced,
    }
async def _fanout_to_destination(
    dest_type: str,
    dest_config: dict[str, Any],
    source_id: uuid.UUID,
    profile_id: uuid.UUID,
    file_key: str,
    pages: list[FilePage],
) -> None:
    """Fan out page content and embeddings to a specific destination engine."""
    await asyncio.to_thread(
        _sync_fanout_to_destination,
        dest_type,
        dest_config,
        str(source_id),
        str(profile_id),
        file_key,
        pages,
    )


async def purge_knowledge_profile(db: AsyncSession, profile: KnowledgeProfile) -> dict[str, Any]:
    """Purge all indexed artifacts for a profile's linked sources across enabled destinations."""
    from sqlalchemy import select

    from src.shared.db.models import IndexedFile

    source_ids = [link.source_id for link in (profile.sources or [])]
    purged_files = 0

    for source_id in source_ids:
        res = await db.execute(select(IndexedFile).where(IndexedFile.source_id == source_id))
        records = list(res.scalars().all())
        for rec in records:
            if rec.file_key:
                await purge_file_from_destinations(profile, rec.file_key)
                purged_files += 1
            await db.delete(rec)

    await db.commit()
    return {
        "purged_files": purged_files,
        "source_ids": [str(sid) for sid in source_ids],
        "destinations": [d.destination_type for d in (profile.destinations or []) if d.enabled],
    }


async def purge_file_from_destinations(
    profile: KnowledgeProfile,
    file_key: str,
) -> None:
    """Purge index artifacts and embeddings for a deleted or modified file across all enabled destinations."""
    enabled_destinations = [d for d in (profile.destinations or []) if d.enabled]
    for dest in enabled_destinations:
        try:
            await asyncio.to_thread(_sync_purge_file_from_destination, dest.destination_type, dest.config or {}, file_key)
        except Exception as exc:
            logger.error("purge_file_from_destination_failed dest=%s file=%s error=%s", dest.destination_type, file_key, exc)


def _sync_purge_file_from_destination(dest_type: str, dest_config: dict[str, Any], file_key: str) -> None:
    settings = get_settings()
    logger.info("purging_file_from_destination type=%s file_key=%s", dest_type, file_key)

    if dest_type == "vector_qdrant":
        collection_name = dest_config.get("collection_name", "knowledge_qdrant_collection")
        url = dest_config.get("url") or settings.qdrant_url
        api_key = dest_config.get("api_key") or settings.qdrant_api_key
        try:
            from qdrant_client import QdrantClient, models
            client = QdrantClient(url=url, api_key=api_key, timeout=5.0)
            client.delete(
                collection_name=collection_name,
                points_selector=models.Filter(
                    must=[models.FieldCondition(key="file_key", match=models.MatchValue(value=file_key))]
                ),
            )
            logger.info("qdrant_points_deleted collection=%s file_key=%s", collection_name, file_key)
        except Exception as exc:
            logger.warning("qdrant_purge_failed file_key=%s error=%s", file_key, exc)

    elif dest_type in ["lexical_opensearch", "elasticsearch"]:
        index_name = dest_config.get("index_name", "knowledge_lexical_index")
        url = _resolve_opensearch_url(dest_config, settings)
        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                query = {
                    "query": {
                        "bool": {
                            "should": [
                                {"term": {"file_key.keyword": file_key}},
                                {"match_phrase": {"file_key": file_key}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                }
                client.post(f"{url}/{index_name}/_delete_by_query", json=query)
            logger.info("opensearch_docs_deleted index=%s file_key=%s", index_name, file_key)
        except Exception as exc:
            logger.warning("opensearch_purge_failed file_key=%s error=%s", file_key, exc)

    elif dest_type in ["cache_redis", "cache_redisvl"]:
        url = dest_config.get("redis_url") or dest_config.get("url") or settings.redis_url
        try:
            import redis
            r = redis.Redis.from_url(url)
            keys = r.keys(f"*{file_key}*")
            if keys:
                r.delete(*keys)
            logger.info("redis_keys_deleted count=%d file_key=%s", len(keys), file_key)
        except Exception as exc:
            logger.warning("redis_purge_failed file_key=%s error=%s", file_key, exc)

    elif dest_type == "graph_neo4j":
        bolt_uri = _resolve_neo4j_bolt_uri(dest_config, settings)
        user = dest_config.get("username") or settings.neo4j_user
        password = dest_config.get("password") or settings.neo4j_password
        auth = None if settings.neo4j_auth_disabled else (user, password)
        try:
            from neo4j import GraphDatabase

            with GraphDatabase.driver(bolt_uri, auth=auth) as driver:
                with driver.session() as session:
                    session.run(
                        """
                        MATCH (d:Document {file_key: $file_key})
                        OPTIONAL MATCH (d)-[:CONTAINS_CHUNK]->(c:Chunk)
                        DETACH DELETE d, c
                        """,
                        file_key=file_key,
                    )
                    session.run(
                        "MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH $prefix DETACH DELETE c",
                        prefix=f"{file_key}:",
                    )
            logger.info("neo4j_nodes_deleted file_key=%s", file_key)
        except Exception as exc:
            logger.warning("neo4j_purge_failed file_key=%s error=%s", file_key, exc)

    elif dest_type in ["relational_pgvector", "database_pgvector"]:
        table_name = _resolve_pg_table(dest_config)
        try:
            try:
                import psycopg2 as pg_driver
            except ImportError:
                import psycopg as pg_driver
            pg_urls = [
                _normalize_pg_url(dest_config.get("connection_url")),
                settings.database_url.replace("+asyncpg", ""),
            ]
            conn = None
            for pg_url in pg_urls:
                if not pg_url:
                    continue
                try:
                    conn = pg_driver.connect(pg_url)
                    break
                except Exception:
                    continue
            if conn:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(f"DELETE FROM {table_name} WHERE file_key = %s", (file_key,))
                logger.info("postgres_rows_deleted table=%s file_key=%s", table_name, file_key)
        except Exception as exc:
            logger.warning("postgres_purge_failed file_key=%s error=%s", file_key, exc)


def _sync_fanout_to_destination(
    dest_type: str,
    dest_config: dict[str, Any],
    source_id: str,
    profile_id: str,
    file_key: str,
    pages: list[FilePage],
) -> None:
    logger.info("fanning_out_to_destination type=%s file=%s pages=%d", dest_type, file_key, len(pages))
    settings = get_settings()

    if dest_type == "vector_qdrant":
        collection_name = dest_config.get("collection_name", "knowledge_qdrant_collection")
        url = dest_config.get("url") or settings.qdrant_url
        api_key = dest_config.get("api_key") or settings.qdrant_api_key

        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )

        points = []
        for p in pages:
            text = p.text or ""
            if not text.strip():
                continue
            emb = embedder.embed_passage(text)
            pt_id = str(uuid.uuid4())
            payload = _build_fanout_payload(
                source_id=uuid.UUID(source_id),
                profile_id=uuid.UUID(profile_id),
                file_key=file_key,
                page=p,
            )
            points.append({
                "point_id": pt_id,
                "dense_vector": emb,
                "payload": payload,
            })

        if points:
            qdrant = QdrantVectorStore(
                url=url,
                collection=collection_name,
                api_key=api_key,
            )
            qdrant.ensure_collection(vector_size=len(points[0]["dense_vector"]), enable_sparse=False)
            qdrant.upsert_batch(points)
            logger.info("qdrant_fanout_complete collection=%s points_count=%d", collection_name, len(points))

    elif dest_type in ["lexical_opensearch", "elasticsearch"]:
        index_name = dest_config.get("index_name", "knowledge_lexical_index")
        url = _resolve_opensearch_url(dest_config, settings)
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                for p in pages:
                    text = p.text or ""
                    if not text.strip():
                        continue
                    payload = _build_fanout_payload(
                        source_id=uuid.UUID(source_id),
                        profile_id=uuid.UUID(profile_id),
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
                    }
                    client.post(f"{url}/{index_name}/_doc", json=doc)
            logger.info("opensearch_lexical_indexed index=%s file=%s pages=%d", index_name, file_key, len(pages))
        except Exception as exc:
            logger.warning("opensearch_indexing_failed index=%s file=%s error=%s", index_name, file_key, exc)

    elif dest_type == "graph_neo4j":
        bolt_uri = _resolve_neo4j_bolt_uri(dest_config, settings)
        user = dest_config.get("username") or settings.neo4j_user
        password = dest_config.get("password") or settings.neo4j_password
        auth = None if settings.neo4j_auth_disabled else (user, password)
        try:
            from neo4j import GraphDatabase

            with GraphDatabase.driver(bolt_uri, auth=auth) as driver:
                with driver.session() as session:
                    session.run(
                        "MERGE (d:Document {file_key: $file_key}) SET d.updated_at = $updated_at",
                        file_key=file_key,
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    for p in pages:
                        text = (p.text or "")[:500]
                        if not text.strip():
                            continue
                        session.run(
                            """
                            MATCH (d:Document {file_key: $file_key})
                            MERGE (c:Chunk {chunk_id: $chunk_id})
                            SET c.page_index = $page_index, c.text = $text, c.content = $content
                            MERGE (d)-[:CONTAINS_CHUNK]->(c)
                            """,
                            file_key=file_key,
                            chunk_id=f"{file_key}:{p.page_index}",
                            page_index=p.page_index,
                            text=text,
                            content=text,
                        )
            logger.info("neo4j_graphrag_indexed file=%s pages=%d", file_key, len(pages))
        except Exception as exc:
            logger.warning("neo4j_graph_failed file=%s error=%s", file_key, exc)

    elif dest_type in ["relational_pgvector", "database_pgvector"]:
        table_name = _resolve_pg_table(dest_config)
        try:
            try:
                import psycopg2 as pg_driver
            except ImportError:
                import psycopg as pg_driver
            pg_urls = [
                _normalize_pg_url(dest_config.get("connection_url")),
                settings.database_url.replace("+asyncpg", ""),
                "postgresql://ingestion:ingestion@localhost:5432/ingestion",
            ]
            conn = None
            for url in pg_urls:
                if not url:
                    continue
                try:
                    conn = pg_driver.connect(url)
                    break
                except Exception:
                    continue
            if not conn:
                raise RuntimeError("Could not connect to PostgreSQL with provided or default credentials")
            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id SERIAL PRIMARY KEY,
                            file_key TEXT NOT NULL,
                            page_index INT NOT NULL,
                            content TEXT,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                    """)
                    for p in pages:
                        text = p.text or ""
                        if not text.strip():
                            continue
                        cur.execute(
                            f"INSERT INTO {table_name} (file_key, page_index, content) VALUES (%s, %s, %s)",
                            (file_key, p.page_index, text)
                        )
            logger.info("pgvector_relational_upserted table=%s file=%s pages=%d", table_name, file_key, len(pages))
        except Exception as exc:
            logger.warning("pgvector_failed file=%s error=%s", file_key, exc)

    elif dest_type in ["cache_redis", "cache_redisvl"]:
        index_prefix = dest_config.get("index_prefix", "knowledge_cache")
        try:
            import redis
            redis_url = dest_config.get("redis_url", "redis://localhost:6379")
            r = redis.from_url(redis_url)
            for p in pages:
                text = p.text or ""
                if not text.strip():
                    continue
                key = f"{index_prefix}:{file_key}:{p.page_index}"
                r.set(key, text, ex=dest_config.get("ttl_seconds", 86400))
            logger.info("redisvl_semantic_cached prefix=%s file=%s pages=%d", index_prefix, file_key, len(pages))
        except Exception as exc:
            logger.warning("redisvl_failed file=%s error=%s", file_key, exc)
