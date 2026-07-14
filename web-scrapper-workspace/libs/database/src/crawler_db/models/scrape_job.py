import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crawler_db.base import Base
from crawler_db.enums import JobStatus


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False),
        nullable=False,
        default=JobStatus.PENDING,
    )
    output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="markdown",
    )
    pages_scraped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    qdrant_collection: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sparse_embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    use_sparse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    crawl_job: Mapped["CrawlJob"] = relationship(back_populates="scrape_jobs")

from crawler_db.models.crawl_job import CrawlJob  # noqa: E402
