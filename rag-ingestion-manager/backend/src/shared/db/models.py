import enum
import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

class Base(AsyncAttrs, DeclarativeBase):
    pass


class FileStatus(str, enum.Enum):
    PROCESSING = "processing"
    SYNCED = "synced"
    FAILED = "failed"
    DELETED = "deleted"
    DUPLICATE = "duplicate"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class JobOperation(str, enum.Enum):
    UPLOAD = "upload"
    APPEND = "append"
    RENAME = "rename"
    DELETE = "delete"


class RagStrategy(str, enum.Enum):
    NAIVE = "naive"
    SPARSE = "sparse"
    HYBRID = "hybrid"
    MULTIMODAL = "multimodal"
    METADATA = "metadata"


class IndexModality(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"


class SourceMonitorMode(str, enum.Enum):
    LIVE = "live"
    SCHEDULED = "scheduled"


class IngestionModality(str, enum.Enum):
    """What an Ingestion Profile sends to the stores.

    TEXT keeps selectable text and tables and ignores images. TEXT_IMAGES adds one
    vision-LLM caption per embedded figure.
    """

    TEXT = "text"
    TEXT_IMAGES = "text_images"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


# Chunking defaults. The Ingestion Profile columns, the profile API and the fanout
# fallback all read these, so a product without a profile chunks like the Pipeline
# form always did.
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 120

# Modality defaults. DEFAULT_TEXT_EMBEDDING_MODEL must name a model the LiteLLM
# proxy serves; the fanout derives the vector dimension from its output.
DEFAULT_TEXT_EMBEDDING_MODEL = "nvidia-embed-textonly"
DEFAULT_CAPTION_MODEL = "groq-vision"
DEFAULT_MODALITY_MODE = "text"
DEFAULT_IMAGE_MIN_PIXELS = 10000


class Directory(Base):
    __tablename__ = "directories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    files: Mapped[list["FileRecord"]] = relationship(back_populates="directory")
    jobs: Mapped[list["SyncJob"]] = relationship(back_populates="directory")


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_directory_content_hash", "directory_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    directory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("directories.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(512))
    stored_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    duplicate_of_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id"), nullable=True
    )
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status", values_callable=_enum_values),
        default=FileStatus.PROCESSING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    directory: Mapped["Directory"] = relationship(back_populates="files", lazy="joined")


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    directory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("directories.id"), index=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    operation: Mapped[JobOperation] = mapped_column(
        Enum(JobOperation, name="job_operation", values_callable=_enum_values)
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=_enum_values),
        default=JobStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    directory: Mapped["Directory"] = relationship(back_populates="jobs")


class ChunkUpload(Base):
    __tablename__ = "chunk_uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    directory_name: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(512))
    total_chunks: Mapped[int] = mapped_column(Integer)
    total_size: Mapped[int] = mapped_column(Integer)
    received_chunks: Mapped[list] = mapped_column(JSONB, default=list)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id"), nullable=True
    )
    operation: Mapped[JobOperation] = mapped_column(
        Enum(JobOperation, name="job_operation", values_callable=_enum_values),
        default=JobOperation.UPLOAD,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(Base):
    """External data source backed by one or more Airbyte connectors via Pathway.

    Each source gets its own dedicated MinIO bucket where connector output lands.
    Multiple connectors can feed into the same source bucket.
    """

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Legacy single-connector fields — kept for backward compat with existing rows.
    # New sources should use the source_connectors relation instead.
    connector_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Connector→Source monitoring mode
    connector_monitor_mode: Mapped[SourceMonitorMode] = mapped_column(
        Enum(SourceMonitorMode, name="source_monitor_mode", values_callable=_enum_values, create_constraint=False),
        default=SourceMonitorMode.LIVE,
    )
    connector_sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_sync_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Source→Pipeline monitoring mode (default for all linked pipelines)
    pipeline_monitor_mode: Mapped[SourceMonitorMode] = mapped_column(
        Enum(SourceMonitorMode, name="source_monitor_mode", values_callable=_enum_values, create_constraint=False),
        default=SourceMonitorMode.LIVE,
    )
    pipeline_sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minio_bucket: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    total_files: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    total_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pipelines: Mapped[list["PipelineSource"]] = relationship(back_populates="source", lazy="selectin")
    connectors: Mapped[list["SourceConnector"]] = relationship(
        back_populates="source", lazy="selectin", cascade="all, delete-orphan"
    )


class SourceConnector(Base):
    """Individual connector attached to a source.

    Each source can have multiple connectors (e.g. Google Drive + Slack feeding
    the same MinIO bucket). Each connector has its own type, config, monitoring
    mode, and sync schedule.
    """

    __tablename__ = "source_connectors"
    __table_args__ = (
        Index("ix_source_connectors_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    connector_type: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    monitor_mode: Mapped[SourceMonitorMode] = mapped_column(
        Enum(SourceMonitorMode, name="source_monitor_mode", values_callable=_enum_values, create_constraint=False),
        default=SourceMonitorMode.LIVE,
    )
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sub-minute scheduled polling. Takes priority over sync_interval_minutes when set.
    sync_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="connectors", lazy="selectin")


class PipelineSource(Base):
    """M2M join between Pipeline and Source with per-link monitoring config."""

    __tablename__ = "pipeline_sources"
    __table_args__ = (
        Index("ix_pipeline_sources_unique", "pipeline_id", "source_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    # Per-link source→pipeline monitoring (overrides source default if set)
    monitor_mode: Mapped[SourceMonitorMode | None] = mapped_column(
        Enum(SourceMonitorMode, name="source_monitor_mode", values_callable=_enum_values, create_constraint=False),
        nullable=True,
    )
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped["Source"] = relationship(back_populates="pipelines", lazy="selectin")
    pipeline: Mapped["Pipeline"] = relationship(back_populates="sources", lazy="selectin")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    rag_strategy: Mapped[RagStrategy] = mapped_column(
        Enum(RagStrategy, name="rag_strategy", values_callable=_enum_values)
    )
    embedding_model: Mapped[str] = mapped_column(String(128))
    sparse_embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    modality: Mapped[IndexModality | None] = mapped_column(
        Enum(IndexModality, name="index_modality", values_callable=_enum_values),
        nullable=True,
    )
    directory_names: Mapped[list] = mapped_column(JSONB, default=list)
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=120)
    qdrant_collection: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    web_scraper_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    scraper_seed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scraper_max_depth: Mapped[int] = mapped_column(Integer, default=2)
    scraper_max_pages: Mapped[int] = mapped_column(Integer, default=50)
    scraper_mode: Mapped[str] = mapped_column(String(32), default="httpx")
    knowledge_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_products.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    sources: Mapped[list["PipelineSource"]] = relationship(back_populates="pipeline", lazy="selectin", cascade="all, delete-orphan")
    knowledge_product: Mapped["KnowledgeProduct | None"] = relationship(
        "KnowledgeProduct", back_populates="pipelines", lazy="selectin"
    )

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=_enum_values, create_constraint=False),
        default=JobStatus.PENDING,
    )
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0)
    points_upserted: Mapped[int] = mapped_column(Integer, default=0)
    scraper_crawl_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scraper_scrape_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="runs")
class KnowledgeProduct(Base):
    """Knowledge product linking MinIO source buckets to multi-sink knowledge destinations."""

    __tablename__ = "knowledge_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    monitor_mode: Mapped[SourceMonitorMode] = mapped_column(
        Enum(
            SourceMonitorMode,
            name="source_monitor_mode",
            values_callable=_enum_values,
            create_constraint=False,
        ),
        default=SourceMonitorMode.SCHEDULED,
        server_default="scheduled",
        nullable=False,
    )
    sync_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingestion_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_profiles.id", ondelete="SET NULL"), nullable=True
    )
    # Hash of the pipeline settings this product last synced with: chunking,
    # modality, embedding and caption model, image threshold. apply-profile
    # compares it, because those settings change what a writer produces without
    # changing a destination config.
    pipeline_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="idle", server_default="idle")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sources: Mapped[list["KnowledgeProductSource"]] = relationship(
        back_populates="knowledge_product", cascade="all, delete-orphan", lazy="selectin"
    )
    destinations: Mapped[list["KnowledgeProductDestination"]] = relationship(
        back_populates="knowledge_product", cascade="all, delete-orphan", lazy="selectin"
    )
    pipelines: Mapped[list["Pipeline"]] = relationship(
        back_populates="knowledge_product", lazy="selectin"
    )
    files: Mapped[list["KnowledgeProductFile"]] = relationship(
        back_populates="knowledge_product", cascade="all, delete-orphan", lazy="selectin"
    )
    ingestion_profile: Mapped["IngestionProfile | None"] = relationship(lazy="selectin")


class KnowledgeProductSource(Base):
    """M2M join between KnowledgeProduct and Source (MinIO bucket)."""

    __tablename__ = "knowledge_product_sources"
    __table_args__ = (
        Index("ix_knowledge_product_sources_unique", "knowledge_product_id", "source_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_products.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge_product: Mapped["KnowledgeProduct"] = relationship(back_populates="sources", lazy="selectin")
    source: Mapped["Source"] = relationship(lazy="selectin")


class KnowledgeProductDestination(Base):
    """Destination configuration for a knowledge product (Qdrant, OpenSearch, pgvector, RedisVL)."""

    __tablename__ = "knowledge_product_destinations"
    __table_args__ = (
        Index("ix_knowledge_product_dest_type_unique", "knowledge_product_id", "destination_type", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_products.id", ondelete="CASCADE"), nullable=False
    )
    destination_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="idle", server_default="idle")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    knowledge_product: Mapped["KnowledgeProduct"] = relationship(back_populates="destinations", lazy="selectin")


class KnowledgeProductFile(Base):
    """Per-product ingestion state for one object in one source bucket.

    This is the fanout's own ledger. It replaces the ``indexed_files`` rows the
    fanout used to write, so that two products sharing a bucket keep separate
    state and so that a per-destination progress record exists for the UI.
    """

    __tablename__ = "knowledge_product_files"
    __table_args__ = (
        Index("ix_kp_files_unique", "knowledge_product_id", "source_id", "file_key", unique=True),
        Index("ix_kp_files_product_status", "knowledge_product_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_products.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    file_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    destinations_synced: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    knowledge_product: Mapped["KnowledgeProduct"] = relationship(back_populates="files")


class IngestionProfile(Base):
    """Reusable ingestion configuration: destination stores plus chunking parameters.

    A Knowledge Product copies these destinations into its own rows at creation,
    so editing a profile never changes a product that already exists.
    """

    __tablename__ = "ingestion_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    chunk_size: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_CHUNK_SIZE, server_default=str(DEFAULT_CHUNK_SIZE)
    )
    chunk_overlap: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_CHUNK_OVERLAP, server_default=str(DEFAULT_CHUNK_OVERLAP)
    )
    modality_mode: Mapped[IngestionModality] = mapped_column(
        Enum(
            IngestionModality,
            name="ingestion_modality",
            values_callable=_enum_values,
            create_constraint=False,
        ),
        default=IngestionModality.TEXT,
        server_default=DEFAULT_MODALITY_MODE,
        nullable=False,
    )
    text_embedding_model: Mapped[str] = mapped_column(
        String(128),
        default=DEFAULT_TEXT_EMBEDDING_MODEL,
        server_default=DEFAULT_TEXT_EMBEDDING_MODEL,
    )
    caption_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_min_pixels: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_IMAGE_MIN_PIXELS, server_default=str(DEFAULT_IMAGE_MIN_PIXELS)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    destinations: Mapped[list["IngestionProfileDestination"]] = relationship(
        back_populates="ingestion_profile", cascade="all, delete-orphan", lazy="selectin"
    )


class IngestionProfileDestination(Base):
    """Destination configuration held by an Ingestion Profile.

    A profile carries no store name: the store identity, the connection values and
    the vector dimension are all derived. The product copy is what assigns
    ``kp_<slug>_<id8>`` to each namespace key.
    """

    __tablename__ = "ingestion_profile_destinations"
    __table_args__ = (
        Index(
            "ix_ingestion_profile_dest_type_unique",
            "ingestion_profile_id",
            "destination_type",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_profiles.id", ondelete="CASCADE"), nullable=False
    )
    destination_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ingestion_profile: Mapped["IngestionProfile"] = relationship(
        back_populates="destinations", lazy="selectin"
    )


class IndexedFile(Base):
    """Tracks which files have been indexed for each pipeline (by content_hash).

    Directory-backed files reference ``files.id`` via ``file_id``. Source-backed
    files (Airbyte connectors dumping into a source MinIO bucket) have no row in
    ``files``; they are identified by ``source_id`` + ``file_key`` instead.
    """

    __tablename__ = "indexed_files"
    __table_args__ = (
        Index("ix_indexed_files_pipeline_content_hash", "pipeline_id", "content_hash", unique=True),
        Index("ix_indexed_files_pipeline_file", "pipeline_id", "file_id"),
        Index("ix_indexed_files_pipeline_source_key", "pipeline_id", "source_id", "file_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True
    )
    file_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
