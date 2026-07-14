import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from crawler_db.enums import JobStatus
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.crawl_result import CrawlResult


class CrawlRepository:
    def create(
        self,
        session: Session,
        *,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        crawl_mode: str = "httpx",
    ) -> CrawlJob:
        job = CrawlJob(
            seed_url=seed_url,
            max_depth=max_depth,
            max_pages=max_pages,
            crawl_mode=crawl_mode,
            status=JobStatus.PENDING,
        )
        session.add(job)
        session.flush()
        return job

    def get(self, session: Session, job_id: uuid.UUID) -> CrawlJob | None:
        stmt = (
            select(CrawlJob)
            .options(selectinload(CrawlJob.result))
            .where(CrawlJob.id == job_id)
        )
        return session.scalar(stmt)

    def list_jobs(self, session: Session, *, limit: int = 20, offset: int = 0) -> list[CrawlJob]:
        stmt = (
            select(CrawlJob)
            .options(selectinload(CrawlJob.result))
            .order_by(CrawlJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(stmt))

    def find_completed_by_config(
        self,
        session: Session,
        *,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        crawl_mode: str,
    ) -> CrawlJob | None:
        stmt = (
            select(CrawlJob)
            .options(selectinload(CrawlJob.result))
            .where(
                CrawlJob.seed_url == seed_url,
                CrawlJob.max_depth == max_depth,
                CrawlJob.max_pages == max_pages,
                CrawlJob.crawl_mode == crawl_mode,
                CrawlJob.status == JobStatus.COMPLETED,
            )
            .order_by(CrawlJob.finished_at.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def update_status(
        self,
        session: Session,
        job: CrawlJob,
        status: JobStatus,
        *,
        error_message: str | None = None,
    ) -> CrawlJob:
        job.status = status
        if error_message is not None:
            job.error_message = error_message
        session.flush()
        return job

    def save_result(
        self,
        session: Session,
        job: CrawlJob,
        *,
        links_file_path: str,
        total_links: int,
        pages_crawled: int,
        metadata: dict | None = None,
    ) -> CrawlResult:
        result = CrawlResult(
            job_id=job.id,
            links_file_path=links_file_path,
            total_links=total_links,
            pages_crawled=pages_crawled,
            metadata_=metadata,
        )
        session.add(result)
        session.flush()
        return result

    def mark_indexing_complete(
        self,
        session: Session,
        job: CrawlJob,
        *,
        embedding_source: str,
    ) -> CrawlJob:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        if embedding_source == "markdown":
            job.markdown_indexed_at = now
        elif embedding_source == "image":
            job.image_indexed_at = now
        else:
            raise ValueError(f"Invalid embedding_source: {embedding_source}")
        session.flush()
        return job
