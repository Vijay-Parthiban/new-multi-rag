"""APScheduler-based cron scheduler for pipeline file sync.

All cron trigger fields are configurable via environment variables
(SYNC_CRON_YEAR, SYNC_CRON_MONTH, SYNC_CRON_DAY, SYNC_CRON_WEEK,
SYNC_CRON_DOW, SYNC_CRON_HOUR, SYNC_CRON_MINUTE, SYNC_CRON_SECOND).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the sync scheduler (does NOT start it)."""
    from src.ingestion_service.core.sync_runner import sync_all_pipelines

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

    logger.info(
        "sync_scheduler_configured trigger=%s",
        trigger,
    )
    return scheduler
