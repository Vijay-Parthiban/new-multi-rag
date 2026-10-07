"""Per-source webscraping: a `*_scrp.txt` manifest in a source bucket becomes `.md` pages.

A manifest is a plain text list of URLs, one per line. While a source has
``webscrape_enabled`` set, every manifest in its bucket is crawled, and each crawled
page is written back into that same bucket as one Markdown object. The Knowledge
Product fanout then ingests those objects on its next tick, so nothing new is needed
on the reader side.

``universal_fanout`` skips the manifests themselves and the generated non-`.md`
objects, so a URL list and a page screenshot never become chunks.
"""

import asyncio
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion_service.clients.scraper import (
    check_scraper_health,
    get_scrape_job,
    get_scrape_page_markdown,
    get_scrape_page_screenshot,
    get_scrape_pages,
    scraper_base_url,
    start_crawl_scrape_pipeline,
)
from src.ingestion_service.core.knowledge_sync import _release_sync_lock
from src.shared.config.settings import Settings, get_settings
from src.shared.db.models import Source, SourceScrapeFile
from src.shared.queue.client import enqueue_webscrape_job, get_redis
from src.shared.storage.s3_client import delete_object, get_object, list_objects, put_object

logger = logging.getLogger(__name__)

MANIFEST_SUFFIX = "_scrp.txt"
PAGE_EXTENSION = ".md"
# Generated pages live under one top-level folder, not beside the manifest. A connector
# sync mirrors its own source into `connectors/<connector_id>/` and DELETES every object
# under that prefix that the remote does not have, so a run folder written there would be
# erased on the next poll.
RUN_ROOT = "webscrape/"
# ponytail: one switch, not a settings field. The scraper already produces the
# full-page PNG for free, so it costs one extra upload per page. Flip to False to
# keep only the Markdown objects.
WEBSCRAPE_STORE_SCREENSHOTS = True

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def is_webscrape_manifest(key: str) -> bool:
    """True when the object name ends with `_scrp.txt`."""
    return key.rsplit("/", 1)[-1].lower().endswith(MANIFEST_SUFFIX)


def output_prefix_for(file_key: str) -> str:
    """Run folder for one manifest: `<RUN_ROOT><dir>/<stem>/`.

    "sites_scrp.txt"                             -> "webscrape/sites_scrp/"
    "connectors/abc/docs/sites_scrp.txt"         -> "webscrape/connectors/abc/docs/sites_scrp/"
    """
    directory, _, filename = file_key.rpartition("/")
    stem = filename[:-4] if filename.lower().endswith(".txt") else filename
    return f"{RUN_ROOT}{directory}/{stem}/" if directory else f"{RUN_ROOT}{stem}/"


def _slugify_url(url: str) -> str:
    """Copy of the scraper's own rule (`page_task._slugify`).

    The two projects share no package, so the rule is repeated here. Keep the
    two in step if either changes.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-").lower()
    return slug[:80] or "page"


def page_object_key(prefix: str, ordinal: int, url: str) -> str:
    return f"{prefix}page-{ordinal:05d}-{_slugify_url(url)}{PAGE_EXTENSION}"


def image_object_key(prefix: str, ordinal: int, url: str) -> str:
    return f"{prefix}images/page-{ordinal:05d}-{_slugify_url(url)}.png"


def parse_seeds(raw: bytes) -> list[str]:
    """Read a manifest into an ordered, de-duplicated list of http(s) URLs.

    ``utf-8-sig`` drops a byte-order mark, because a manifest written by a Windows
    editor carries one and would otherwise hide the first URL.
    """
    seeds: list[str] = []
    seen: set[str] = set()
    for line in raw.decode("utf-8-sig", errors="replace").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if not candidate.lower().startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        seeds.append(candidate)
    return seeds


def drop_webscrape_control_objects(remote: dict[str, Any]) -> int:
    """Remove the manifests and their non-Markdown run-folder objects from a listing.

    A `*_scrp.txt` object is a URL list, not content: the pages it produces are the
    content. Its run folder also holds page screenshots, which must not reach a text
    index. Dropping a key here also makes the fanout's delete sweep purge any ledger
    row for it, which is how a manifest indexed before this rule existed is cleaned up.

    Returns the number of keys dropped. Mutates ``remote`` in place.
    """
    manifests = [key for key in remote if is_webscrape_manifest(key)]
    if not manifests:
        return 0
    prefixes = tuple(output_prefix_for(key) for key in manifests)
    dropped = 0
    for key in list(remote):
        if is_webscrape_manifest(key) or (
            key.startswith(prefixes) and not key.lower().endswith(PAGE_EXTENSION)
        ):
            remote.pop(key)
            dropped += 1
    return dropped


def _is_stale(row: SourceScrapeFile, settings: Settings) -> bool:
    """True when a row that never finished has not been touched for longer than a job lives.

    ``updated_at`` moves on every commit, and the scrape commits once per page, so a running
    job always looks fresh. Only a job that died reaches this age, which is what makes the
    reconciler able to retry it without a live poller piling up duplicates.
    """
    if row.updated_at is None:
        return True
    age_seconds = (datetime.now(UTC) - row.updated_at).total_seconds()
    return age_seconds > settings.webscrape_job_timeout_seconds + 300


def scrape_error_detail(exc: Exception) -> str:
    """Turn a failed seed into one line that names the cause.

    httpx reports a dead service as "All connection attempts failed", which says nothing
    about which service. A transport error therefore names the scraper and its URL.
    """
    if isinstance(exc, httpx.TransportError):
        return f"no answer from the scraper API at {scraper_base_url()} ({type(exc).__name__})"
    return str(exc)


async def _purge_prefix(bucket: str, prefix: str) -> int:
    """Delete every object under one run folder. Returns the count deleted."""
    try:
        objects = await list_objects(bucket, prefix)
    except Exception as exc:
        logger.error("webscrape_purge_list_failed bucket=%s prefix=%s error=%s", bucket, prefix, exc)
        return 0
    deleted = 0
    for obj in objects:
        key = getattr(obj, "key", "")
        if not key:
            continue
        await delete_object(bucket, key)
        deleted += 1
    if deleted:
        logger.info("webscrape_prefix_purged bucket=%s prefix=%s objects=%d", bucket, prefix, deleted)
    return deleted


async def scan_source_manifests(
    db: AsyncSession, source: Source, *, force: bool = False
) -> dict[str, Any]:
    """Detect the manifests of one source, enqueue the changed ones, purge the removed ones.

    With the switch off, nothing is detected and no generated object is touched, so
    turning the switch off never deletes output.

    ``force`` re-runs a manifest whose etag and size are unchanged even when its last run
    finished. The page's Rescan button uses it, so a failed run can be retried without
    touching the file. The automatic paths leave it false, so they stay change-driven.
    """
    if not source.webscrape_enabled:
        return {"status": "disabled", "queued": 0, "removed": 0}
    bucket = source.minio_bucket
    if not bucket:
        return {"status": "no_bucket", "queued": 0, "removed": 0}

    try:
        objects = await list_objects(bucket)
    except Exception as exc:
        logger.error("webscrape_list_failed source=%s bucket=%s error=%s", source.id, bucket, exc)
        return {"status": "error", "queued": 0, "removed": 0, "message": str(exc)}

    manifests = {
        getattr(obj, "key", ""): obj
        for obj in objects
        if getattr(obj, "key", "") and is_webscrape_manifest(getattr(obj, "key", ""))
    }

    res = await db.execute(select(SourceScrapeFile).where(SourceScrapeFile.source_id == source.id))
    rows = {row.file_key: row for row in res.scalars().all()}

    queued = 0
    settings = get_settings()
    for key, obj in manifests.items():
        etag = str(getattr(obj, "etag", "") or "")
        size = int(getattr(obj, "size", 0) or 0)
        row = rows.get(key)
        if not force and row is not None and row.etag == etag and row.size_bytes == size:
            # Nothing changed, so only a row that no run owns may be enqueued again.
            # A live connector poller calls this scan on every cycle, so a row that is
            # mid-run must not be re-enqueued: that would pile up one job per poll.
            if row.status in {"success", "failed"} or not _is_stale(row, settings):
                continue
        if row is None:
            row = SourceScrapeFile(source_id=source.id, file_key=key, status="pending")
            db.add(row)
            rows[key] = row
        elif row.status != "running":
            # A run in flight owns these fields, so the scan leaves them alone: the page
            # would otherwise read "pending" while the job is mid-crawl. The Redis lock,
            # not the scan, decides whether a second attempt may start.
            row.status = "pending"
            row.error_message = None
        row.etag = etag
        row.size_bytes = size
        await db.commit()
        await enqueue_webscrape_job(row.id)
        queued += 1
        logger.info("webscrape_manifest_queued source=%s file_key=%s", source.id, key)

    removed = 0
    for key, row in list(rows.items()):
        if key in manifests:
            continue
        await _purge_prefix(bucket, output_prefix_for(key))
        await db.delete(row)
        await db.commit()
        removed += 1
        logger.info("webscrape_manifest_removed source=%s file_key=%s", source.id, key)

    return {"status": "ok", "queued": queued, "removed": removed}


async def scan_source_manifests_by_id(source_id: uuid.UUID) -> dict[str, Any]:
    """Open a session and scan one source. Safe to run as a background task."""
    from src.shared.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            source = await db.get(Source, source_id)
            if source is None:
                return {"status": "error", "message": f"Source {source_id} not found"}
            return await scan_source_manifests(db, source)
    except Exception as exc:
        logger.error("webscrape_scan_failed source=%s error=%s", source_id, exc)
        return {"status": "error", "message": str(exc)}


async def scan_all_webscrape_sources() -> dict[str, Any]:
    """Reconcile every source with the switch on. The missed-event safety net."""
    from src.shared.db.session import AsyncSessionLocal

    totals = {"sources": 0, "queued": 0, "removed": 0}
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Source.id).where(Source.webscrape_enabled.is_(True)))
            source_ids = list(res.scalars().all())
    except Exception as exc:
        logger.error("webscrape_reconcile_failed error=%s", exc)
        return {"status": "error", "message": str(exc), **totals}

    for source_id in source_ids:
        result = await scan_source_manifests_by_id(source_id)
        totals["sources"] += 1
        totals["queued"] += int(result.get("queued") or 0)
        totals["removed"] += int(result.get("removed") or 0)

    logger.info(
        "webscrape_reconcile_done sources=%d queued=%d removed=%d",
        totals["sources"],
        totals["queued"],
        totals["removed"],
    )
    return {"status": "ok", **totals}


async def _poll_scrape_job(scrape_job_id: str, settings: Settings) -> str:
    """Wait for one scrape job to finish. Returns its status, or "timeout"."""
    deadline = time.monotonic() + settings.webscrape_job_timeout_seconds
    while True:
        job = await get_scrape_job(scrape_job_id)
        status = str(job.get("status") or "")
        if status in _TERMINAL_STATUSES:
            return status
        if time.monotonic() > deadline:
            logger.error(
                "webscrape_scrape_job_timeout scrape_job=%s status=%s timeout_s=%d",
                scrape_job_id,
                status,
                settings.webscrape_job_timeout_seconds,
            )
            return "timeout"
        await asyncio.sleep(settings.webscrape_poll_seconds)


async def _scrape_seed(
    db: AsyncSession,
    source: Source,
    row: SourceScrapeFile,
    settings: Settings,
    seed: str,
    prefix: str,
    ordinal: int,
) -> int:
    """Crawl one seed URL and write its pages into the bucket. Returns the pages written."""
    result = await start_crawl_scrape_pipeline(
        seed_url=seed,
        max_depth=int(source.webscrape_max_depth or 0),
        max_pages=int(source.webscrape_max_pages or 50),
        mode="httpx",
        embedding_source="none",
        qdrant_collection=None,
        embedding_model=None,
        sparse_embedding_model=None,
        pipeline_description=f"source-webscrape:{source.name}",
        use_sparse=False,
    )
    scrape_job_id = str((result.get("scrape_job") or {}).get("id") or "")
    if not scrape_job_id:
        logger.warning("webscrape_scrape_job_missing seed=%s result=%s", seed, result)
        raise RuntimeError(str(result.get("skip_reason") or "no scrape job in the scraper response"))

    status = await _poll_scrape_job(scrape_job_id, settings)
    if status != "completed":
        raise RuntimeError(f"scrape job {scrape_job_id} ended as {status}")

    payload = await get_scrape_pages(scrape_job_id)
    written = 0
    for page in payload.get("pages") or []:
        index = int(page["index"])
        url = str(page.get("url") or seed)
        text = await get_scrape_page_markdown(scrape_job_id, index)
        key = page_object_key(prefix, ordinal, url)
        await put_object(source.minio_bucket, key, text.encode("utf-8"))
        generated = list(row.generated_keys or [])
        generated.append(key)
        if WEBSCRAPE_STORE_SCREENSHOTS:
            screenshot = await get_scrape_page_screenshot(scrape_job_id, index)
            image_key = image_object_key(prefix, ordinal, url)
            await put_object(source.minio_bucket, image_key, screenshot)
            generated.append(image_key)
        # Reassign the JSONB column so the change is tracked, then commit per page
        # so pages_scraped is observable while the job runs.
        row.generated_keys = generated
        row.pages_scraped = int(row.pages_scraped or 0) + 1
        await db.commit()
        ordinal += 1
        written += 1
    logger.info(
        "webscrape_seed_done source=%s seed=%s scrape_job=%s pages=%d",
        source.id,
        seed,
        scrape_job_id,
        written,
    )
    return written


async def _run_scrape(
    db: AsyncSession, source: Source, row: SourceScrapeFile, settings: Settings
) -> dict[str, Any]:
    bucket = source.minio_bucket
    if not bucket:
        row.status = "failed"
        row.error_message = "Source has no MinIO bucket"
        row.completed_at = datetime.now(UTC)
        await db.commit()
        return {"status": "error", "message": row.error_message}

    row.status = "running"
    row.error_message = None
    await db.commit()

    try:
        raw = await get_object(bucket, row.file_key)
    except Exception as exc:
        row.status = "failed"
        row.error_message = f"Manifest unreadable: {exc}"
        row.completed_at = datetime.now(UTC)
        await db.commit()
        logger.error("webscrape_manifest_unreadable key=%s error=%s", row.file_key, exc)
        return {"status": "error", "message": row.error_message}

    seeds = parse_seeds(raw)
    if len(seeds) > settings.webscrape_max_seeds:
        logger.warning(
            "webscrape_seed_limit file=%s total=%d limit=%d",
            row.file_key,
            len(seeds),
            settings.webscrape_max_seeds,
        )
        seeds = seeds[: settings.webscrape_max_seeds]

    prefix = output_prefix_for(row.file_key)
    # Probe the scraper before the purge. A dead scraper must not delete the pages an
    # earlier run produced, and one probe beats one connection error per URL.
    try:
        await check_scraper_health()
    except Exception as exc:
        row.status = "failed"
        row.error_message = scrape_error_detail(exc)
        row.completed_at = datetime.now(UTC)
        await db.commit()
        logger.error("webscrape_scraper_unreachable file=%s error=%s", row.file_key, exc)
        return {"status": "error", "message": row.error_message, "seeds": len(seeds)}
    # Purge before write: a changed manifest regenerates the whole run folder.
    await _purge_prefix(bucket, prefix)
    row.seeds_planned = len(seeds)
    row.pages_scraped = 0
    row.generated_keys = []
    await db.commit()

    if not seeds:
        row.status = "failed"
        row.error_message = "No http(s) URL in the manifest"
        row.completed_at = datetime.now(UTC)
        await db.commit()
        return {"status": "error", "message": row.error_message, "seeds": 0}

    errors: list[str] = []
    ordinal = 0
    for seed in seeds:
        try:
            ordinal += await _scrape_seed(db, source, row, settings, seed, prefix, ordinal)
        except Exception as exc:
            errors.append(f"{seed}: {scrape_error_detail(exc)}")
            logger.error("webscrape_seed_failed source=%s seed=%s error=%s", source.id, seed, exc)

    row.error_message = "; ".join(errors)[:4000] or None
    row.status = "success" if int(row.pages_scraped or 0) > 0 else "failed"
    row.completed_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "webscrape_job_finished source=%s file_key=%s status=%s pages=%d errors=%d",
        source.id,
        row.file_key,
        row.status,
        row.pages_scraped,
        len(errors),
    )

    if row.status == "success":
        # Local import: pathway_sync imports this module, so a module-level import
        # would be circular. The codebase uses the same pattern in pipeline_runner.
        from src.ingestion_service.core.pathway_sync import _trigger_pipeline_syncs

        await _trigger_pipeline_syncs(db, source)

    return {
        "status": row.status,
        "pages_scraped": int(row.pages_scraped or 0),
        "seeds": len(seeds),
        "errors": len(errors),
    }


async def run_source_scrape_job(db: AsyncSession, scrape_file_id: uuid.UUID) -> dict[str, Any]:
    """Drain one queued manifest: crawl its seeds and write the pages back to the bucket."""
    row = await db.get(SourceScrapeFile, scrape_file_id)
    if row is None:
        logger.warning("webscrape_job_missing scrape_file=%s", scrape_file_id)
        return {"status": "error", "message": "Scrape file row not found"}

    source = await db.get(Source, row.source_id)
    if source is None:
        return {"status": "error", "message": "Source not found"}
    if not source.webscrape_enabled:
        return {"status": "skipped", "message": "Webscraping is off for this source."}

    settings = get_settings()
    # The API and the worker can both reach this row, and the reconciler re-enqueues
    # it every ten minutes. One cross-process lock keeps two runs off one run folder.
    lock_key = f"webscrape:job:lock:{scrape_file_id}"
    lock_token = uuid.uuid4().hex
    lock = await get_redis()
    acquired = await lock.set(
        lock_key, lock_token, nx=True, ex=settings.webscrape_job_timeout_seconds + 300
    )
    if not acquired:
        logger.info("webscrape_job_locked_elsewhere scrape_file=%s", scrape_file_id)
        return {"status": "skipped", "message": "Another process is scraping this manifest."}

    try:
        return await _run_scrape(db, source, row, settings)
    finally:
        await _release_sync_lock(lock, lock_key, lock_token)
