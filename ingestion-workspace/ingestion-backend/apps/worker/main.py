import asyncio
import logging

from apps.worker.scheduler import create_scheduler
from src.file_manager.core.operations import run_job
from src.file_manager.utils.paths import ensure_storage_layout
from src.ingestion_service.core.pipeline_runner import run_pipeline_job
from src.ingestion_service.core.sync_runner import sync_pipeline
from src.shared.db.session import AsyncSessionLocal, close_db
from src.shared.queue.client import close_redis, dequeue_job, dequeue_pipeline_run, dequeue_sync_run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    ensure_storage_layout()
    logger.info("Worker started — file_manager:jobs + ingestion:pipeline:jobs + ingestion:sync:jobs")

    while True:
        handled = False

        job_id = await dequeue_job(timeout=2)
        if job_id:
            handled = True
            logger.info("Processing sync job %s", job_id)
            async with AsyncSessionLocal() as db:
                try:
                    await run_job(db, job_id)
                    logger.info("Sync job %s finished", job_id)
                except Exception:
                    logger.exception("Sync job %s failed", job_id)

        run_id = await dequeue_pipeline_run(timeout=2)
        if run_id:
            handled = True
            logger.info("Processing pipeline run %s", run_id)
            async with AsyncSessionLocal() as db:
                try:
                    await run_pipeline_job(db, run_id)
                    logger.info("Pipeline run %s finished", run_id)
                except Exception:
                    logger.exception("Pipeline run %s failed", run_id)

        pipeline_id = await dequeue_sync_run(timeout=2)
        if pipeline_id:
            handled = True
            logger.info("Processing sync for pipeline %s", pipeline_id)
            async with AsyncSessionLocal() as db:
                try:
                    await sync_pipeline(db, pipeline_id)
                    logger.info("Pipeline sync %s finished", pipeline_id)
                except Exception:
                    logger.exception("Pipeline sync %s failed", pipeline_id)

        if not handled:
            await asyncio.sleep(0.1)


async def main() -> None:
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Sync scheduler started")
    try:
        await worker_loop()
    finally:
        scheduler.shutdown(wait=False)
        await close_redis()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
