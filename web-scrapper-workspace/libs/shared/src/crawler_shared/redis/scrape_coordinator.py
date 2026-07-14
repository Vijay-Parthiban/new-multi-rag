import json
import logging
from typing import Any

from crawler_shared.redis.client import get_redis_connection

logger = logging.getLogger(__name__)

_PREFIX = "scrape:job:"


def _key(scrape_job_id: str, suffix: str) -> str:
    return f"{_PREFIX}{scrape_job_id}:{suffix}"


def init_scrape_job(scrape_job_id: str, *, total_pages: int) -> None:
    """Reset Redis counters and result storage for a scrape job."""
    redis = get_redis_connection()
    redis.set(_key(scrape_job_id, "total"), total_pages)
    redis.set(_key(scrape_job_id, "completed"), 0)
    redis.delete(_key(scrape_job_id, "finalize_scheduled"))
    pattern = _key(scrape_job_id, "result:*")
    for key in redis.scan_iter(match=pattern):
        redis.delete(key)
    logger.info("scrape_job_initialized scrape_job_id=%s total=%d", scrape_job_id, total_pages)


def save_page_result(scrape_job_id: str, *, index: int, payload: dict[str, Any]) -> None:
    redis = get_redis_connection()
    redis.set(_key(scrape_job_id, f"result:{index}"), json.dumps(payload, ensure_ascii=False))


def load_page_results(scrape_job_id: str) -> list[dict[str, Any]]:
    redis = get_redis_connection()
    total = int(redis.get(_key(scrape_job_id, "total")) or 0)
    results: list[dict[str, Any]] = []
    for index in range(total):
        raw = redis.get(_key(scrape_job_id, f"result:{index}"))
        if raw is None:
            continue
        results.append(json.loads(raw))
    results.sort(key=lambda item: item.get("index", 0))
    return results


def mark_page_finished(scrape_job_id: str) -> bool:
    """Increment completed count. Returns True if this was the last page."""
    redis = get_redis_connection()
    completed = int(redis.incr(_key(scrape_job_id, "completed")))
    total = int(redis.get(_key(scrape_job_id, "total")) or 0)
    logger.info(
        "scrape_page_finished scrape_job_id=%s completed=%d total=%d",
        scrape_job_id,
        completed,
        total,
    )
    return completed >= total


def try_schedule_finalize(scrape_job_id: str) -> bool:
    """Return True if this caller should enqueue the finalize task (once only)."""
    redis = get_redis_connection()
    scheduled = redis.set(_key(scrape_job_id, "finalize_scheduled"), "1", nx=True)
    return bool(scheduled)


def cleanup_scrape_job(scrape_job_id: str) -> None:
    redis = get_redis_connection()
    for suffix in ("total", "completed", "finalize_scheduled"):
        redis.delete(_key(scrape_job_id, suffix))
    for key in redis.scan_iter(match=_key(scrape_job_id, "result:*")):
        redis.delete(key)
