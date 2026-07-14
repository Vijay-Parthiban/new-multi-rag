import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crawler_db.base import Base
from crawler_db.enums import JobStatus

if TYPE_CHECKING:
    from crawler_db.models.crawl_result import CrawlResult
    from crawler_db.models.scrape_job import ScrapeJob


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    crawl_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="httpx", server_default="httpx")
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False),
        nullable=False,
        default=JobStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    markdown_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def markdown_ingested(self) -> bool:
        return self.markdown_indexed_at is not None

    @property
    def image_ingested(self) -> bool:
        return self.image_indexed_at is not None

    result: Mapped["CrawlResult | None"] = relationship(back_populates="job", uselist=False)
    scrape_jobs: Mapped[list["ScrapeJob"]] = relationship(back_populates="crawl_job")
