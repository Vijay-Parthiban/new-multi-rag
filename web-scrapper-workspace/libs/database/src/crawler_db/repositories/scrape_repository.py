import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from crawler_db.enums import JobStatus
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.scrape_job import ScrapeJob


class ScrapeRepository:
    def create(
        self,
        session: Session,
        *,
        crawl_job_id: uuid.UUID,
        embedding_source: str = "markdown",
        qdrant_collection: str | None = None,
        embedding_model: str | None = None,
        sparse_embedding_model: str | None = None,
        pipeline_description: str | None = None,
        use_sparse: bool = True,
    ) -> ScrapeJob:
        job = ScrapeJob(
            crawl_job_id=crawl_job_id,
            status=JobStatus.PENDING,
            embedding_source=embedding_source,
            qdrant_collection=qdrant_collection,
            embedding_model=embedding_model,
            sparse_embedding_model=sparse_embedding_model,
            pipeline_description=pipeline_description,
            use_sparse=use_sparse,
        )
        session.add(job)
        session.flush()
        return job

    def get(self, session: Session, job_id: uuid.UUID) -> ScrapeJob | None:
        stmt = (
            select(ScrapeJob)
            .options(selectinload(ScrapeJob.crawl_job).selectinload(CrawlJob.result))
            .where(ScrapeJob.id == job_id)
        )
        return session.scalar(stmt)

    def update_status(
        self,
        session: Session,
        job: ScrapeJob,
        status: JobStatus,
        *,
        error_message: str | None = None,
        output_dir: str | None = None,
        pages_scraped: int | None = None,
    ) -> ScrapeJob:
        job.status = status
        if error_message is not None:
            job.error_message = error_message
        if output_dir is not None:
            job.output_dir = output_dir
        if pages_scraped is not None:
            job.pages_scraped = pages_scraped
        session.flush()
        return job

    def list_scrapes(self, session: Session, limit: int = 20, offset: int = 0) -> list[ScrapeJob]:
        return (
            session.query(ScrapeJob)
            .order_by(ScrapeJob.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def find_completed_for_crawl(
        self,
        session: Session,
        *,
        crawl_job_id: uuid.UUID,
        embedding_source: str,
        qdrant_collection: str | None = None,
    ) -> ScrapeJob | None:
        conditions = [
            ScrapeJob.crawl_job_id == crawl_job_id,
            ScrapeJob.embedding_source == embedding_source,
            ScrapeJob.status == JobStatus.COMPLETED,
        ]
        if qdrant_collection is not None:
            conditions.append(ScrapeJob.qdrant_collection == qdrant_collection)
        stmt = (
            select(ScrapeJob)
            .where(*conditions)
            .order_by(ScrapeJob.finished_at.desc())
            .limit(1)
        )
        return session.scalar(stmt)
