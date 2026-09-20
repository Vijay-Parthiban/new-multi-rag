"""Knowledge Product sync scheduling.

One poller task per enabled product. The poller owns the fanout: the source
poller only enqueues pipeline runs and kicks this module, so the fanout never
runs twice for one source change.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src.shared.db.models import KnowledgeProduct, KnowledgeProductSource, SourceMonitorMode

logger = logging.getLogger(__name__)

_KNOWLEDGE_POLLER_TASKS: dict[uuid.UUID, asyncio.Task] = {}
_SYNCING_PRODUCTS: set[uuid.UUID] = set()

LIVE_INTERVAL_SECONDS = 3
DEFAULT_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 5


def resolved_interval_seconds(product: KnowledgeProduct) -> int:
    """Poll interval for one product, in seconds.

    Live mode is 3 s. A scheduled product uses its own interval, and the
    five-second floor keeps a typo from hammering the bucket.
    """
    if product.monitor_mode == SourceMonitorMode.LIVE:
        return LIVE_INTERVAL_SECONDS
    if product.sync_interval_seconds:
        return max(MIN_INTERVAL_SECONDS, int(product.sync_interval_seconds))
    if product.sync_interval_minutes:
        return max(MIN_INTERVAL_SECONDS, int(product.sync_interval_minutes) * 60)
    return DEFAULT_INTERVAL_SECONDS


def stop_knowledge_poller(product_id: uuid.UUID) -> None:
    """Stop and cancel the poller task for a product, if one runs."""
    task = _KNOWLEDGE_POLLER_TASKS.pop(product_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("knowledge_poller_stopped product=%s", product_id)


async def register_knowledge_poller(product_id: uuid.UUID) -> None:
    """Register or re-register the poller for one product.

    Re-reads the product every time, so a change to the monitor mode, the
    interval, the source links or a destination's enabled flag takes effect at
    once. It always fires one immediate sync so a new product does not wait.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.shared.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(KnowledgeProduct)
            .options(
                selectinload(KnowledgeProduct.sources).selectinload(KnowledgeProductSource.source),
                selectinload(KnowledgeProduct.destinations),
            )
            .where(KnowledgeProduct.id == product_id)
        )
        product = res.scalar_one_or_none()

        stop_knowledge_poller(product_id)

        if product is None:
            logger.info("knowledge_poller_skipped product=%s reason=no_product", product_id)
            return
        if not product.enabled:
            logger.info("knowledge_poller_skipped product=%s reason=disabled", product_id)
            return
        if not [s for s in (product.sources or []) if s.source]:
            logger.info("knowledge_poller_skipped product=%s reason=no_sources", product_id)
            return
        if not [d for d in (product.destinations or []) if d.enabled]:
            logger.info("knowledge_poller_skipped product=%s reason=all_destinations_paused", product_id)
            return

        interval_seconds = resolved_interval_seconds(product)
        logger.info(
            "knowledge_poller_started product=%s mode=%s interval=%ds destinations=%d sources=%d",
            product_id,
            product.monitor_mode.value if hasattr(product.monitor_mode, "value") else product.monitor_mode,
            interval_seconds,
            len([d for d in (product.destinations or []) if d.enabled]),
            len([s for s in (product.sources or []) if s.source]),
        )

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await sync_knowledge_product(product_id)
                except asyncio.CancelledError:
                    logger.info("knowledge_poller_cancelled product=%s", product_id)
                    break
                except Exception as exc:
                    logger.error("knowledge_poller_error product=%s error=%s", product_id, exc)

        _KNOWLEDGE_POLLER_TASKS[product_id] = asyncio.create_task(_loop())

    # Outside the session: the first sync must not hold this session open.
    asyncio.create_task(sync_knowledge_product(product_id))


async def sync_knowledge_product(product_id: uuid.UUID) -> dict[str, Any]:
    """Run one fanout tick for a product, with status bookkeeping.

    A second call while one runs returns at once, so a burst of source events
    cannot start competing fanouts over the same ledger rows.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from src.ingestion_service.core.universal_fanout import execute_universal_fanout_sync
    from src.shared.db.session import AsyncSessionLocal

    if product_id in _SYNCING_PRODUCTS:
        logger.info("knowledge_sync_already_in_progress product=%s", product_id)
        return {"status": "skipped", "message": "A sync is already running for this product."}

    _SYNCING_PRODUCTS.add(product_id)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(KnowledgeProduct)
                .options(
                    selectinload(KnowledgeProduct.sources).selectinload(KnowledgeProductSource.source),
                    selectinload(KnowledgeProduct.destinations),
                )
                .where(KnowledgeProduct.id == product_id)
            )
            product = res.scalar_one_or_none()
            if product is None:
                return {"status": "error", "message": f"Product {product_id} not found"}

            product.status = "syncing"
            await db.commit()

            try:
                result = await execute_universal_fanout_sync(db, product)
            except Exception as exc:
                logger.exception("knowledge_sync_failed product=%s", product_id)
                product.status = "error"
                product.error_message = str(exc)
                await db.commit()
                raise

            now = datetime.now(UTC)
            product.status = "idle"
            product.last_sync_at = now
            product.error_message = None
            for dest in product.destinations or []:
                if dest.enabled:
                    dest.status = "idle"
                    dest.last_sync_at = now
                    dest.error_message = None
            await db.commit()
            return result
    finally:
        _SYNCING_PRODUCTS.discard(product_id)


async def init_all_knowledge_pollers() -> None:
    """Start a poller for every enabled product at server startup."""
    try:
        from sqlalchemy import select

        from src.shared.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            res = await db.execute(select(KnowledgeProduct.id).where(KnowledgeProduct.enabled.is_(True)))
            product_ids = list(res.scalars().all())

        for product_id in product_ids:
            await register_knowledge_poller(product_id)
        logger.info("init_all_knowledge_pollers_started count=%d", len(product_ids))
    except Exception as exc:
        logger.error("init_all_knowledge_pollers_startup_error error=%s", exc)
