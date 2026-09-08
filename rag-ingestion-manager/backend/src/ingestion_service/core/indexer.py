import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.ingestion_service.embeddings.client import EmbeddingClient
from src.ingestion_service.embeddings.sparse_client import get_sparse_embedding_client
from src.ingestion_service.types import FILE_INGEST_SOURCE_TYPE
from src.ingestion_service.utils.text_splitter import chunk_text
from src.ingestion_service.vector.qdrant_store import QdrantVectorStore
from src.shared.config.settings import get_settings
from src.shared.db.models import IndexModality, Pipeline, RagStrategy

logger = logging.getLogger(__name__)


@dataclass
class IndexContext:
    pipeline: Pipeline
    run_id: uuid.UUID
    collection: str


def _use_sparse(strategy: RagStrategy, modality: IndexModality) -> bool:
    if strategy in {RagStrategy.SPARSE, RagStrategy.HYBRID}:
        return True
    if strategy in {RagStrategy.MULTIMODAL, RagStrategy.METADATA} and modality == IndexModality.TEXT:
        return True
    return False


def _needs_modality(strategy: RagStrategy) -> bool:
    return strategy in {RagStrategy.MULTIMODAL, RagStrategy.METADATA}


def _resolve_modality(pipeline: Pipeline) -> IndexModality:
    if pipeline.modality:
        return pipeline.modality
    return IndexModality.TEXT


def _build_payload(
    *,
    ctx: IndexContext,
    file_id: uuid.UUID,
    file_name: str,
    directory_name: str,
    mime_type: str | None,
    page_index: int,
    chunk_index: int,
    content: str,
    point_type: str,
    embedding_source: str,
    relative_path: str | None,
) -> dict:
    settings = get_settings()
    base: dict = {
        "source_type": FILE_INGEST_SOURCE_TYPE,
        "source_id": str(ctx.run_id),
        "source_locator": f"{directory_name}/{file_name}#page-{page_index}",
        "pipeline_id": str(ctx.pipeline.id),
        "file_id": str(file_id),
        "directory_name": directory_name,
        "original_name": file_name,
        "mime_type": mime_type,
        "relative_path": relative_path,
        "page_index": page_index,
        "embedding_source": embedding_source,
        "type": point_type,
        "content": content,
        "chunk_index": chunk_index,
        "title": file_name,
        "pipeline_description": ctx.pipeline.description,
        "rag_strategy": ctx.pipeline.rag_strategy.value,
        "embedding_model": ctx.pipeline.embedding_model,
        "sparse_embedding_model": ctx.pipeline.sparse_embedding_model or settings.sparse_embedding_model,
        "chunk_size": ctx.pipeline.chunk_size,
        "chunk_overlap": ctx.pipeline.chunk_overlap,
        "modality": ctx.pipeline.modality.value if ctx.pipeline.modality else None,
    }
    return base


class FileIndexer:
    def __init__(self, ctx: IndexContext) -> None:
        settings = get_settings()
        self._ctx = ctx
        self._store = QdrantVectorStore(
            url=settings.qdrant_url,
            collection=ctx.collection,
            api_key=settings.qdrant_api_key,
        )
        model = ctx.pipeline.embedding_model
        if _resolve_modality(ctx.pipeline) == IndexModality.IMAGE:
            model = ctx.pipeline.embedding_model
        self._embedder = EmbeddingClient(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=model,
        )
        self._sparse = None
        modality = _resolve_modality(ctx.pipeline)
        if _use_sparse(ctx.pipeline.rag_strategy, modality):
            sparse_model = ctx.pipeline.sparse_embedding_model or settings.sparse_embedding_model
            if not sparse_model:
                raise ValueError("sparse_embedding_model is required for sparse/hybrid/metadata strategies")
            self._sparse = get_sparse_embedding_client(sparse_model)
        self._collection_ready = False

    def index_text_page(
        self,
        *,
        file_id: uuid.UUID,
        file_name: str,
        directory_name: str,
        mime_type: str | None,
        page_index: int,
        text: str,
        relative_path: str | None,
    ) -> int:
        """
        Chunks and indexes a single page of text, extracting dense and (optionally) sparse
        embeddings for each chunk before upserting them to the Qdrant vector store.

        Args:
            file_id: The UUID mapping to the source document.
            file_name: Original document filename.
            directory_name: Parent directory mapping.
            mime_type: File schema type.
            page_index: Numeric index of the page inside the multi-page document.
            text: Raw extracted UTF-8 string for this page.
            relative_path: The filesystem relative object path.

        Returns:
            The number of vector points successfully upserted from this page.
        """
        chunks = chunk_text(text, self._ctx.pipeline.chunk_size, self._ctx.pipeline.chunk_overlap)
        if not chunks:
            return 0

        points: list[dict] = []
        modality = _resolve_modality(self._ctx.pipeline)
        use_sparse = _use_sparse(self._ctx.pipeline.rag_strategy, modality)

        for chunk_idx, chunk in enumerate(chunks):
            dense = self._embedder.embed_passage(chunk)
            if not self._collection_ready:
                self._store.ensure_collection(len(dense), enable_sparse=use_sparse)
                self._collection_ready = True

            sparse = self._sparse.embed(chunk) if use_sparse and self._sparse else None
            raw_id = f"{self._ctx.run_id}:{file_id}:p{page_index}:c{chunk_idx}"
            points.append(
                {
                    "point_id": raw_id,
                    "dense_vector": dense,
                    "sparse_vector": sparse,
                    "payload": _build_payload(
                        ctx=self._ctx,
                        file_id=file_id,
                        file_name=file_name,
                        directory_name=directory_name,
                        mime_type=mime_type,
                        page_index=page_index,
                        chunk_index=chunk_idx,
                        content=chunk,
                        point_type="text",
                        embedding_source="markdown",
                        relative_path=relative_path,
                    ),
                }
            )

        self._store.upsert_batch(points)
        return len(points)

    def index_image_page(
        self,
        *,
        file_id: uuid.UUID,
        file_name: str,
        directory_name: str,
        mime_type: str | None,
        page_index: int,
        image_png: bytes,
        relative_path: str | None,
    ) -> int:
        """
        Retrieves multimodal dense embeddings directly from a rasterized PDF page PNG buffer 
        and stores the data URI base64 chunk representation natively alongside it in Qdrant.
        Allows downstream vision LLMs to answer directly from native document structure without OCR.

        Returns:
            Number of vectors upserted (always 1 per page).
        """
        dense = self._embedder.embed_image_png(image_png)
        if not self._collection_ready:
            self._store.ensure_collection(len(dense), enable_sparse=False)
            self._collection_ready = True

        data_uri = EmbeddingClient.image_to_data_uri(image_png)
        raw_id = f"{self._ctx.run_id}:{file_id}:p{page_index}:image"
        self._store.upsert_batch(
            [
                {
                    "point_id": raw_id,
                    "dense_vector": dense,
                    "sparse_vector": None,
                    "payload": _build_payload(
                        ctx=self._ctx,
                        file_id=file_id,
                        file_name=file_name,
                        directory_name=directory_name,
                        mime_type=mime_type,
                        page_index=page_index,
                        chunk_index=0,
                        content=data_uri,
                        point_type="image",
                        embedding_source="image",
                        relative_path=relative_path,
                    ),
                }
            ]
        )
        return 1

    def index_file(
        self,
        *,
        file_path: Path,
        file_id: uuid.UUID,
        file_name: str,
        directory_name: str,
        mime_type: str | None,
        relative_path: str | None,
        pages,
    ) -> tuple[int, int]:
        """Process yielded pages; returns (pages_indexed, points_upserted)."""
        from src.ingestion_service.core.page_yielder import FilePage

        modality = _resolve_modality(self._ctx.pipeline)
        pages_count = 0
        points_count = 0

        for page in pages:
            if not isinstance(page, FilePage):
                continue
            pages_count += 1

            if modality == IndexModality.IMAGE:
                if not page.image_png:
                    logger.warning("No image for page %d in %s", page.page_index, file_name)
                    continue
                points_count += self.index_image_page(
                    file_id=file_id,
                    file_name=file_name,
                    directory_name=directory_name,
                    mime_type=mime_type,
                    page_index=page.page_index,
                    image_png=page.image_png,
                    relative_path=relative_path,
                )
            else:
                points_count += self.index_text_page(
                    file_id=file_id,
                    file_name=file_name,
                    directory_name=directory_name,
                    mime_type=mime_type,
                    page_index=page.page_index,
                    text=page.text,
                    relative_path=relative_path,
                )

        return pages_count, points_count


def validate_pipeline_config(pipeline: Pipeline) -> None:
    if not pipeline.qdrant_collection:
        raise ValueError("qdrant_collection is required for every pipeline.")
    if not pipeline.description:
        raise ValueError("description is required for every pipeline.")
    if not pipeline.directory_names and not pipeline.web_scraper_enabled and not pipeline.sources:
        raise ValueError("Select at least one folder, enable web scraper, or link a source.")
    if _needs_modality(pipeline.rag_strategy) and not pipeline.modality:
        raise ValueError("Multimodal and metadata strategies require a modality (text or image).")
    modality = _resolve_modality(pipeline)
    settings = get_settings()
    if _use_sparse(pipeline.rag_strategy, modality) and not (pipeline.sparse_embedding_model or settings.sparse_embedding_model):
        raise ValueError("sparse_embedding_model is required for sparse/hybrid/metadata strategies.")
    if pipeline.web_scraper_enabled and not pipeline.scraper_seed_url:
        raise ValueError("Web scraper requires a seed URL.")
