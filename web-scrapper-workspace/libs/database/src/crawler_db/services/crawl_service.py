import uuid
from datetime import UTC, datetime
import logging

from sqlalchemy.orm import Session

from crawler_db.enums import JobStatus
from crawler_db.models.crawl_job import CrawlJob
from crawler_db.models.scrape_job import ScrapeJob
from crawler_db.repositories.crawl_repository import CrawlRepository
from crawler_db.repositories.scrape_repository import ScrapeRepository

logger = logging.getLogger(__name__)


class CrawlService:
    def __init__(self) -> None:
        """Business rules for crawl jobs (create/start/complete/fail/list)."""
        self._repo = CrawlRepository()

    def create_crawl_job(
        self,
        session: Session,
        *,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        crawl_mode: str = "httpx",
    ) -> CrawlJob:
        if crawl_mode not in {"httpx", "playwright", "auto"}:
            raise ValueError("crawl_mode must be one of: httpx, playwright, auto")
        job = self._repo.create(
            session,
            seed_url=seed_url,
            max_depth=max_depth,
            max_pages=max_pages,
            crawl_mode=crawl_mode,
        )
        logger.info(
            "crawl_job_db_created id=%s seed_url=%s max_depth=%d max_pages=%d mode=%s",
            job.id,
            job.seed_url,
            job.max_depth,
            job.max_pages,
            job.crawl_mode,
        )
        return job

    def get_job(self, session: Session, job_id: uuid.UUID) -> CrawlJob | None:
        return self._repo.get(session, job_id)

    def list_jobs(self, session: Session, *, limit: int = 20, offset: int = 0) -> list[CrawlJob]:
        return self._repo.list_jobs(session, limit=limit, offset=offset)

    def find_completed_crawl_by_config(
        self,
        session: Session,
        *,
        seed_url: str,
        max_depth: int,
        max_pages: int,
        crawl_mode: str = "httpx",
    ) -> CrawlJob | None:
        return self._repo.find_completed_by_config(
            session,
            seed_url=seed_url,
            max_depth=max_depth,
            max_pages=max_pages,
            crawl_mode=crawl_mode,
        )

    def start_crawl(self, session: Session, job_id: uuid.UUID) -> CrawlJob:
        job = self._require_job(session, job_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.flush()
        logger.info("crawl_job_db_started id=%s", job_id)
        return job

    def complete_crawl(
        self,
        session: Session,
        job_id: uuid.UUID,
        *,
        links_file_path: str,
        total_links: int,
        pages_crawled: int,
        metadata: dict | None = None,
    ) -> CrawlJob:
        job = self._require_job(session, job_id)
        self._repo.save_result(
            session,
            job,
            links_file_path=links_file_path,
            total_links=total_links,
            pages_crawled=pages_crawled,
            metadata=metadata,
        )
        job.status = JobStatus.COMPLETED
        job.finished_at = datetime.now(UTC)
        session.flush()
        logger.info(
            "crawl_job_db_completed id=%s pages_crawled=%d total_links=%d links_file_path=%s",
            job_id,
            pages_crawled,
            total_links,
            links_file_path,
        )
        return job

    def fail_crawl(self, session: Session, job_id: uuid.UUID, error_message: str) -> CrawlJob:
        job = self._require_job(session, job_id)
        self._repo.update_status(session, job, JobStatus.FAILED, error_message=error_message)
        job.finished_at = datetime.now(UTC)
        session.flush()
        logger.info("crawl_job_db_failed id=%s error=%s", job_id, error_message)
        return job

    def _require_job(self, session: Session, job_id: uuid.UUID) -> CrawlJob:
        job = self._repo.get(session, job_id)
        if job is None:
            raise ValueError(f"Crawl job not found: {job_id}")
        return job


class ScrapeService:
    def __init__(self) -> None:
        """Business rules for scrape jobs sourced from completed crawl results."""
        self._crawl_repo = CrawlRepository()
        self._scrape_repo = ScrapeRepository()
    
    def list_scrapes(
        self, 
        session: Session, 
        *, 
        limit: int = 20, 
        offset: int = 0
    ) -> list[ScrapeJob]:
        """Fetch a paginated list of scrape jobs from the database (newest first)."""
        
        return self._scrape_repo.list_scrapes(session, limit=limit, offset=offset)

    def create_scrape_job(
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
        crawl_job = self._crawl_repo.get(session, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")
        if crawl_job.status != JobStatus.COMPLETED:
            raise ValueError(f"Crawl job {crawl_job_id} is not completed")
        if crawl_job.result is None:
            raise ValueError(f"Crawl job {crawl_job_id} has no result")
        return self._create_scrape_job_record(
            session,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,
            qdrant_collection=qdrant_collection,
            embedding_model=embedding_model,
            sparse_embedding_model=sparse_embedding_model,
            pipeline_description=pipeline_description,
            use_sparse=use_sparse,
        )

    def create_pending_scrape_job(
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
        """Create a scrape job before its crawl finishes (used by crawl-and-scrape pipelines)."""
        crawl_job = self._crawl_repo.get(session, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")
        return self._create_scrape_job_record(
            session,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,
            qdrant_collection=qdrant_collection,
            embedding_model=embedding_model,
            sparse_embedding_model=sparse_embedding_model,
            pipeline_description=pipeline_description,
            use_sparse=use_sparse,
        )

    def _ensure_indexing_allowed(
        self,
        session: Session,
        crawl_job: CrawlJob,
        embedding_source: str,
        qdrant_collection: str | None,
    ) -> None:
        if qdrant_collection:
            existing = self._scrape_repo.find_completed_for_crawl(
                session,
                crawl_job_id=crawl_job.id,
                embedding_source=embedding_source,
                qdrant_collection=qdrant_collection,
            )
            if existing:
                raise ValueError(
                    f"Crawl job {crawl_job.id} already indexed to collection "
                    f"{qdrant_collection} for {embedding_source}"
                )
            return
        if embedding_source == "markdown" and crawl_job.markdown_ingested:
            raise ValueError(
                f"Crawl job {crawl_job.id} already has markdown vectors indexed at "
                f"{crawl_job.markdown_indexed_at.isoformat()}"
            )
        if embedding_source == "image" and crawl_job.image_ingested:
            raise ValueError(
                f"Crawl job {crawl_job.id} already has image vectors indexed at "
                f"{crawl_job.image_indexed_at.isoformat()}"
            )

    def is_embedding_source_indexed(self, crawl_job: CrawlJob, embedding_source: str) -> bool:
        if embedding_source == "markdown":
            return crawl_job.markdown_ingested
        if embedding_source == "image":
            return crawl_job.image_ingested
        raise ValueError(f"Invalid embedding_source: {embedding_source}")

    def find_completed_scrape_for_crawl(
        self,
        session: Session,
        *,
        crawl_job_id: uuid.UUID,
        embedding_source: str,
        qdrant_collection: str | None = None,
    ) -> ScrapeJob | None:
        return self._scrape_repo.find_completed_for_crawl(
            session,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,
            qdrant_collection=qdrant_collection,
        )

    def mark_crawl_indexing_complete(
        self,
        session: Session,
        crawl_job_id: uuid.UUID,
        *,
        embedding_source: str,
    ) -> CrawlJob:
        crawl_job = self._crawl_repo.get(session, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")
        return self._crawl_repo.mark_indexing_complete(
            session,
            crawl_job,
            embedding_source=embedding_source,
        )

    def _create_scrape_job_record(
        self,
        session: Session,
        *,
        crawl_job_id: uuid.UUID,
        embedding_source: str,
        qdrant_collection: str | None = None,
        embedding_model: str | None = None,
        sparse_embedding_model: str | None = None,
        pipeline_description: str | None = None,
        use_sparse: bool = True,
    ) -> ScrapeJob:
        if embedding_source not in {"markdown", "image"}:
            raise ValueError(f"Invalid embedding_source: {embedding_source}")
        crawl_job = self._crawl_repo.get(session, crawl_job_id)
        if crawl_job is None:
            raise ValueError(f"Crawl job not found: {crawl_job_id}")
        self._ensure_indexing_allowed(
            session,
            crawl_job,
            embedding_source,
            qdrant_collection,
        )
        job = self._scrape_repo.create(
            session,
            crawl_job_id=crawl_job_id,
            embedding_source=embedding_source,
            qdrant_collection=qdrant_collection,
            embedding_model=embedding_model,
            sparse_embedding_model=sparse_embedding_model,
            pipeline_description=pipeline_description,
            use_sparse=use_sparse,
        )
        logger.info("scrape_job_db_created id=%s crawl_job_id=%s", job.id, crawl_job_id)
        return job

    def get_job(self, session: Session, job_id: uuid.UUID) -> ScrapeJob | None:
        return self._scrape_repo.get(session, job_id)

    def start_scrape(self, session: Session, job_id: uuid.UUID) -> ScrapeJob:
        job = self._require_job(session, job_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.flush()
        logger.info("scrape_job_db_started id=%s", job_id)
        return job

    def complete_scrape(
        self,
        session: Session,
        job_id: uuid.UUID,
        *,
        output_dir: str,
        pages_scraped: int,
    ) -> ScrapeJob:
        job = self._require_job(session, job_id)
        self._scrape_repo.update_status(
            session,
            job,
            JobStatus.COMPLETED,
            output_dir=output_dir,
            pages_scraped=pages_scraped,
        )
        job.finished_at = datetime.now(UTC)
        session.flush()
        logger.info("scrape_job_db_completed id=%s pages_scraped=%d output_dir=%s", job_id, pages_scraped, output_dir)
        return job

    def fail_scrape(self, session: Session, job_id: uuid.UUID, error_message: str) -> ScrapeJob:
        job = self._require_job(session, job_id)
        self._scrape_repo.update_status(session, job, JobStatus.FAILED, error_message=error_message)
        job.finished_at = datetime.now(UTC)
        session.flush()
        logger.info("scrape_job_db_failed id=%s error=%s", job_id, error_message)
        return job

    def _require_job(self, session: Session, job_id: uuid.UUID) -> ScrapeJob:
        job = self._scrape_repo.get(session, job_id)
        if job is None:
            raise ValueError(f"Scrape job not found: {job_id}")
        return job
