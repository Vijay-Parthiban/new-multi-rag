"""APScheduler-based cron scheduler for pipeline file sync.

All cron trigger fields are configurable via environment variables
(SYNC_CRON_YEAR, SYNC_CRON_MONTH, SYNC_CRON_DAY, SYNC_CRON_WEEK,
SYNC_CRON_DOW, SYNC_CRON_HOUR, SYNC_CRON_MINUTE, SYNC_CRON_SECOND).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the sync scheduler (does NOT start it)."""
    from src.ingestion_service.core.sync_runner import sync_all_pipelines
    from src.ingestion_service.core.webscrape import scan_all_webscrape_sources
    from src.ingestion_service.clients.source_sync import sync_all_enabled_sources

    settings = get_settings()
    scheduler = AsyncIOScheduler()

    trigger = CronTrigger(
        year=settings.sync_cron_year,
        month=settings.sync_cron_month,
        day=settings.sync_cron_day,
        week=settings.sync_cron_week,
        day_of_week=settings.sync_cron_dow,
        hour=settings.sync_cron_hour,
        minute=settings.sync_cron_minute,
        second=settings.sync_cron_second,
    )

    scheduler.add_job(
        sync_all_pipelines,
        trigger,
        id="pipeline_file_sync",
        name="Pipeline File Sync (cron)",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_all_enabled_sources,
        trigger,
        id="source_connector_sync",
        name="Source Connector Sync (cron)",
        replace_existing=True,
    )

    # The webscrape reconciler. A connector sync and a manual upload both scan the
    # bucket, but a missed event or a lost enqueue would otherwise leave a manifest
    # unprocessed, so one pass every few minutes closes the gap.
    scheduler.add_job(
        scan_all_webscrape_sources,
        IntervalTrigger(minutes=settings.webscrape_reconcile_minutes),
        id="webscrape_reconcile",
        name="Source Webscrape Reconcile",
        replace_existing=True,
    )
    logger.info(
        "sync_scheduler_configured trigger=%s webscrape_reconcile_minutes=%d",
        trigger,
        settings.webscrape_reconcile_minutes,
    )
    return scheduler
