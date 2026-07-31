"""Pathway worker entrypoint — source syncing + scheduled polling.

Usage:
    python -m pathway_worker.main
"""

import asyncio
import logging

from pathway_worker.syncer import run_source_sync_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the source sync loop (continuous polling)."""
    logger.info("pathway_worker_starting")
    try:
        await run_source_sync_loop()
    except KeyboardInterrupt:
        logger.info("pathway_worker_shutdown")
    except Exception:
        logger.exception("pathway_worker_crash")


if __name__ == "__main__":
    asyncio.run(main())