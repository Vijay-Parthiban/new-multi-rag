import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crawler_db.base import Base


class CrawlResult(Base):
    __tablename__ = "crawl_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    links_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    total_links: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["CrawlJob"] = relationship(back_populates="result")

from crawler_db.models.crawl_job import CrawlJob  # noqa: E402
