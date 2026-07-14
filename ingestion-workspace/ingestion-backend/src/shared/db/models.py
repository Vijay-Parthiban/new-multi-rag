import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
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


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="pipeline")


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


class IndexedFile(Base):
    """Tracks which files have been indexed for each pipeline (by content_hash)."""

    __tablename__ = "indexed_files"
    __table_args__ = (
        Index("ix_indexed_files_pipeline_content_hash", "pipeline_id", "content_hash", unique=True),
        Index("ix_indexed_files_pipeline_file", "pipeline_id", "file_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
