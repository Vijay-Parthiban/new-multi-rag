"""Pathway Airbyte connector sync — sync sources to MinIO and trigger pipeline re-index.

This module is the integration point between Airbyte connectors (run via Pathway)
and the pipeline ingestion system. It:
1. Runs the Airbyte connector via Pathway to pull data from external sources
2. Writes connector output to the source's dedicated MinIO bucket
3. Updates source status, last_sync_at, etc.
4. Optionally enqueues pipeline re-indexing for pipelines linked to the source
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.shared.config.settings import get_settings
from src.shared.db.models import Source

logger = logging.getLogger(__name__)


async def sync_source_from_pathway(db: AsyncSession, source_id: uuid.UUID) -> None:
    """Sync a source through Pathway Airbyte connector.

    This is the main entrypoint called by the pathway worker.
    """
    source = await db.get(Source, source_id, options=(selectinload(Source.pipelines),))
    if not source:
        logger.error("pathway_sync_source_not_found source=%s", source_id)
        return

    if not source.enabled:
        logger.info("pathway_sync_skipped_disabled source=%s", source.id)
        return

    source.status = "syncing"
    source.error_message = None
    await db.commit()

    try:
        # Run the Airbyte connector via Pathway — output lands in the source's MinIO bucket
        connector_config = {
            "connector_type": source.connector_type,
            "config": source.config or {},
            "bucket": source.minio_bucket,
            "monitor_mode": source.monitor_mode.value,
        }
        result = await _run_airbyte_connector(connector_config)

        source.status = "connected"
        source.last_sync_at = datetime.now(UTC)
        source.error_message = None
        await db.commit()

        logger.info(
            "pathway_sync_success source=%s connector=%s files=%s",
            source.id,
            source.connector_type,
            result.get("files_written", 0),
        )

        # Trigger pipeline re-indexing for linked pipelines
        await _trigger_pipeline_syncs(db, source)

    except Exception as exc:
        logger.exception("pathway_sync_failed source=%s", source.id)
        source.status = "error"
        source.error_message = str(exc)[:1024]
        source.last_sync_at = datetime.now(UTC)
        await db.commit()


async def _run_airbyte_connector(config: dict) -> dict:
    """Run the Airbyte connector through Pathway.

    Uses Pathway to stream data from the Airbyte source connector and write
    output files to the dedicated MinIO bucket. Returns sync metadata.

    The connector config is forwarded directly to Pathway, which manages:
    - Airbyte connector lifecycle (install, configure, run)
    - Streaming data processing
    - Output fanout to MinIO files
    """
    settings = get_settings()

    # The Pathway pipeline reads from Airbyte and writes to MinIO
    # For now we call the external Pathway service endpoint.
    # In production this would use pathway-sdk directly.
    import httpx

    pathway_url = f"{settings.scraper_api_url.rstrip('/')}/pathway/sync-source"

    payload = {
        "connector_type": config["connector_type"],
        "config": config["config"],
        "bucket_name": config["bucket"],
        "monitor_mode": config["monitor_mode"],
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(pathway_url, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "pathway_connector_complete connector=%s bucket=%s",
            config["connector_type"],
            config["bucket"],
        )
        return result


async def _trigger_pipeline_syncs(db: AsyncSession, source: "Source") -> None:
    """Enqueue sync jobs for all pipelines linked to this source."""
    from src.shared.queue.client import enqueue_sync_run

    for link in source.pipelines:
        pipeline_id = link.pipeline_id
        logger.info(
            "pathway_triggering_pipeline_sync source=%s pipeline=%s",
            source.id,
            pipeline_id,
        )
        await enqueue_sync_run(pipeline_id)