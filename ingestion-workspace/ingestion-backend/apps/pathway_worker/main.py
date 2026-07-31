import asyncio
import logging

from src.ingestion_service.core.pathway_sync import sync_source_from_pathway
from src.shared.db.session import AsyncSessionLocal, close_db
from src.shared.queue.client import close_redis, dequeue_pathway_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def pathway_worker_loop() -> None:
    """Main loop for Pathway Airbyte connector worker.

    This worker polls the pathway_queue, processes source syncs, and updates
    source status/timestamps in the database.
    """
    logger.info("Pathway worker started — pathway:sync:jobs")

    while True:
        handled = False

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
