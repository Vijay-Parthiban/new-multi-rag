import asyncio
import logging

from src.ingestion_service.core.pathway_sync import sync_source_from_pathway
from src.shared.db.session import AsyncSessionLocal, close_db
from src.shared.queue.client import close_redis, dequeue_pathway_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def pathway_worker_loop() -> None:
    """Main loop for Pathway Airbyte connector worker.

    This worker polls the pathway_queue for on-demand sync jobs, and periodically
    executes differential CRUD syncs for scheduled active sources into MinIO and Knowledge Destinations.
    """
    logger.info("Pathway worker started — pathway:sync:jobs")
    last_scheduled_check = 0.0

    while True:
        handled = False

        # 1. Process queued sync requests
        source_id = await dequeue_pathway_sync(timeout=2)
        if source_id:
            handled = True
            logger.info("Processing pathway sync for source %s", source_id)
            async with AsyncSessionLocal() as db:
                try:
                    await sync_source_from_pathway(db, source_id)
                    logger.info("Pathway sync for source %s finished", source_id)
                except Exception:
                    logger.exception("Pathway sync for source %s failed", source_id)

        # 2. Periodic poll check for scheduled sources (every 10 seconds)
        now_ts = asyncio.get_event_loop().time()
        if now_ts - last_scheduled_check > 10.0:
            last_scheduled_check = now_ts
            try:
                from sqlalchemy import select
                from src.shared.db.models import Source
                async with AsyncSessionLocal() as db:
                    stmt = select(Source).where(Source.enabled == True)
                    res = await db.execute(stmt)
                    sources = res.scalars().all()
                    for src in sources:
                        if src.status != "syncing":
                            await sync_source_from_pathway(db, src.id)
            except Exception as exc:
                logger.warning("scheduled_source_poll_failed error=%s", exc)

        if not handled:
            await asyncio.sleep(0.1)

async def main() -> None:
    try:
        await pathway_worker_loop()
    finally:
        await close_redis()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
