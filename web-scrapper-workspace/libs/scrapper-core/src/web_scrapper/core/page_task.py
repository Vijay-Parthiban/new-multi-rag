import asyncio
import base64
import logging
import re
import uuid
from dataclasses import dataclass

from qdrant_client.models import PointStruct

from crawler_shared.config import Settings
from crawler_shared.types import EmbeddingSource, WEB_SCRAPE_SOURCE_TYPE

from web_scrapper.utils.text_splitter import chunk_markdown
from web_scrapper.core.playwright_scraper import PlaywrightPageScraper, PlaywrightScrapeResult
from web_scrapper.embeddings.chunk_embedder import embed_markdown_chunks_parallel
from web_scrapper.embeddings.client import EmbeddingClient
from web_scrapper.embeddings.sparse_client import get_sparse_embedding_client
from web_scrapper.storage.artifacts import build_page_record
from web_scrapper.vector.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


@dataclass
class ScrapeVectorConfig:
    qdrant_collection: str | None = None
    embedding_model: str | None = None
    sparse_embedding_model: str | None = None
    pipeline_description: str | None = None
    use_sparse: bool = True


def _slugify(url: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-").lower()
    return slug[:100] or "page"


def stem_for_index(index: int, url: str) -> str:
    return f"{index:05d}-{_slugify(url)}"


async def _scrape_url(settings: Settings, url: str) -> PlaywrightScrapeResult:
    scraper = PlaywrightPageScraper(timeout_ms=settings.playwright_timeout_ms)
    return await scraper.scrape(url)


def _resolve_vector_config(settings: Settings, vector_config: ScrapeVectorConfig | None) -> ScrapeVectorConfig:
    cfg = vector_config or ScrapeVectorConfig()
    return ScrapeVectorConfig(
        qdrant_collection=cfg.qdrant_collection or settings.qdrant_collection,
        embedding_model=cfg.embedding_model or settings.embedding_model,
        sparse_embedding_model=cfg.sparse_embedding_model or settings.sparse_embedding_model,
        pipeline_description=cfg.pipeline_description,
        use_sparse=cfg.use_sparse,
    )


async def process_scrape_page(
    settings: Settings,
    *,
    scrape_job_id: str,
    crawl_job_id: str,
    embedding_source: EmbeddingSource,
    url: str,
    index: int,
    depth: int,
    parent: str | None,
    stem: str,
    vector_config: ScrapeVectorConfig | None = None,
) -> dict[str, object]:
    """Scrape one URL, chunk markdown or embed screenshot, upsert vectors to Qdrant."""
    try:
        resolved = _resolve_vector_config(settings, vector_config)
        output_root = settings.scrape_data_dir / scrape_job_id
        markdown_path = output_root / "markdown" / f"{stem}.md"
        screenshot_path = output_root / "screenshots" / f"{stem}.png"

        page = await _scrape_url(settings, url)
        screenshot_b64 = base64.b64encode(page.screenshot_bytes).decode("ascii")

        from web_scrapper.storage.artifacts import PageInMemory

        in_memory = PageInMemory(
            index=index,
            url=page.url,
            depth=depth,
            parent=parent,
            title=page.title,
            markdown=page.markdown,
            screenshot_bytes=page.screenshot_bytes,
            markdown_path=markdown_path,
            screenshot_path=screenshot_path,
            output_root=output_root,
        )
        include_image_base64 = embedding_source == "image"
        record = build_page_record(in_memory, include_image_base64=include_image_base64)

        embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=resolved.embedding_model,
        )

        base_payload = {
            "source_type": WEB_SCRAPE_SOURCE_TYPE,
            "source_id": scrape_job_id,
            "source_locator": page.url,
            "scrape_job_id": scrape_job_id,
            "crawl_job_id": crawl_job_id,
            "url": page.url,
            "depth": depth,
            "parent": parent,
            "embedding_source": embedding_source,
            "markdown_uri": record.markdown_uri,
            "screenshot_uri": record.screenshot_uri,
            "screenshot_file_uri": str(screenshot_path.resolve()),
            "title": page.title,
        }
        if resolved.pipeline_description:
            base_payload["pipeline_description"] = resolved.pipeline_description

        collection = resolved.qdrant_collection
        qdrant = QdrantVectorStore(url=settings.qdrant_url, collection=collection)
        points_to_upsert: list[PointStruct] = []

        if embedding_source == "markdown":
            chunks = chunk_markdown(page.markdown, chunk_size=1000, chunk_overlap=120)
            sparse_embedder = None
            if resolved.use_sparse:
                sparse_embedder = get_sparse_embedding_client(resolved.sparse_embedding_model)
            chunk_vectors = embed_markdown_chunks_parallel(
                chunks=chunks,
                embedder=embedder,
                sparse_embedder=sparse_embedder,
                max_workers=settings.scrape_embed_workers,
            )

            for chunk_idx, chunk_result in enumerate(chunk_vectors):
                chunk_text = chunks[chunk_idx]
                dense_vector = chunk_result[0]
                sparse_vector = chunk_result[1] if len(chunk_result) > 1 else None

                raw_id = f"{scrape_job_id}:{page.url}:chunk-{chunk_idx}"
                point_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))

                chunk_payload = base_payload.copy()
                chunk_payload["type"] = "text"
                chunk_payload["content"] = chunk_text
                chunk_payload["chunk_index"] = chunk_idx

                vector_payload: dict[str, object] = {"dense": dense_vector}
                if sparse_vector is not None:
                    vector_payload["sparse"] = sparse_vector

                points_to_upsert.append(
                    PointStruct(
                        id=point_uuid,
                        vector=vector_payload,  # type: ignore[arg-type]
                        payload=chunk_payload,
                    )
                )
        else:
            vector = embedder.embed_image_png(page.screenshot_bytes)

            raw_id = f"{scrape_job_id}:{page.url}:image"
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))

            image_payload = base_payload.copy()
            image_payload["type"] = "image"
            image_payload["content"] = f"data:image/png;base64,{screenshot_b64}"
            image_payload["chunk_index"] = 0

            points_to_upsert.append(
                PointStruct(
                    id=point_uuid,
                    vector={"dense": vector},  # type: ignore[arg-type]
                    payload=image_payload,
                )
            )

        if points_to_upsert:
            dense_size = len(points_to_upsert[0].vector["dense"])  # type: ignore[index]
            qdrant.ensure_collection(dense_size, enable_sparse=resolved.use_sparse)
            qdrant.client.upsert(
                collection_name=collection,
                points=points_to_upsert,
            )

        logger.info(
            "scrape_page_processed scrape_job_id=%s index=%d url=%s embedding_source=%s collection=%s points_count=%d",
            scrape_job_id,
            index,
            page.url,
            embedding_source,
            collection,
            len(points_to_upsert),
        )

        return {
            "success": True,
            "index": index,
            "url": page.url,
            "depth": depth,
            "parent": parent,
            "title": page.title,
            "markdown": page.markdown,
            "screenshot_b64": screenshot_b64,
            "markdown_uri": record.markdown_uri,
            "screenshot_uri": record.screenshot_uri,
            "screenshot_file_uri": record.screenshot_file_uri,
            "image_base64": record.image_base64,
            "stem": stem,
        }

    except Exception as exc:
        logger.error("scrape_page_failed url=%s error=%s", url, str(exc), exc_info=True)
        return failed_page_payload(
            index=index,
            url=url,
            depth=depth,
            parent=parent,
            stem=stem,
            error=str(exc),
        )


def failed_page_payload(
    *,
    index: int,
    url: str,
    depth: int,
    parent: str | None,
    stem: str,
    error: str,
) -> dict[str, object]:
    return {
        "success": False,
        "index": index,
        "url": url,
        "depth": depth,
        "parent": parent,
        "title": None,
        "markdown": "",
        "screenshot_b64": "",
        "markdown_uri": f"markdown/{stem}.md",
        "screenshot_uri": f"screenshots/{stem}.png",
        "screenshot_file_uri": "",
        "image_base64": None,
        "stem": stem,
        "error": error,
    }
