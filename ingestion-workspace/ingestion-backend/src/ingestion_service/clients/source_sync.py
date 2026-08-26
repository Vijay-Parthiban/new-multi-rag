"""Client for triggering Pathway-based Airbyte source connector syncs.

This is called by the API layer when a user wants to manually trigger
a source sync, or by the scheduled worker for cron-based syncs.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def trigger_source_sync(db: AsyncSession, source_id: uuid.UUID) -> dict[str, Any]:
    """Trigger an Airbyte connector sync for a single source.

    This updates the source status and is meant to be called from the
    API or from a scheduler. The actual sync is handled by the Pathway
    worker, which polls the DB.

    Returns a dict with the sync status.
    """
    from src.shared.db.models import Source

    source = await db.get(Source, source_id)
    if not source:
        return {"status": "error", "message": f"Source {source_id} not found"}

    if not source.enabled:
        return {"status": "error", "message": "Source is disabled"}

    # Update status to indicate sync attempt
    source.status = "syncing"
    source.error_message = None
    await db.commit()

    # Enqueue the pathway sync job so the pathway worker picks it up
    from src.shared.queue.client import enqueue_pathway_sync

    await enqueue_pathway_sync(source_id)

    logger.info(
        "source_sync_triggered id=%s name=%s type=%s",
        source.id, source.name, source.connector_type,
    )

    return {
        "status": "triggered",
        "source_id": str(source_id),
        "connector_type": source.connector_type,
        "minio_bucket": source.minio_bucket,
    }


async def sync_all_enabled_sources() -> list[dict[str, Any]]:
    """Trigger syncs for all enabled sources.

    This is intended for the cron scheduler pathway.
    Returns summary results.
    """
    from src.shared.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        from src.shared.db.models import Source

        result = await db.execute(
            select(Source).where(
                Source.enabled.is_(True),
                Source.status.in_(["disconnected", "connected", "idle"]),
            )
        )
        sources = result.scalars().all()

        results: list[dict[str, Any]] = []
        for source in sources:
            try:
                res = await trigger_source_sync(db, source.id)
                results.append(res)
            except Exception as exc:
                logger.exception("source_sync_one_failed id=%s", source.id)
                results.append({
                    "status": "error",
                    "source_id": str(source.id),
                    "message": str(exc),
                })

    logger.info("source_sync_all_complete count=%d", len(results))
    return results