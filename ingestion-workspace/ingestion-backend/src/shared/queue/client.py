import json
import uuid

import redis.asyncio as aioredis

from src.shared.config.settings import get_settings

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def enqueue_job(job_id: uuid.UUID) -> None:
    settings = get_settings()
    client = await get_redis()
    await client.lpush(settings.file_manager_queue, json.dumps({"job_id": str(job_id)}))


async def enqueue_pipeline_run(run_id: uuid.UUID) -> None:
    settings = get_settings()
    client = await get_redis()
    await client.lpush(settings.pipeline_queue, json.dumps({"run_id": str(run_id)}))


async def dequeue_job(timeout: int = 5) -> uuid.UUID | None:
    settings = get_settings()
    client = await get_redis()
    try:
        result = await client.brpop(settings.file_manager_queue, timeout=timeout)
    except aioredis.TimeoutError:
        return None
    if not result:
        return None
    payload = json.loads(result[1])
    return uuid.UUID(payload["job_id"])


async def dequeue_pipeline_run(timeout: int = 5) -> uuid.UUID | None:
    settings = get_settings()
    client = await get_redis()
    try:
        result = await client.brpop(settings.pipeline_queue, timeout=timeout)
    except aioredis.TimeoutError:
        return None
    if not result:
        return None
    payload = json.loads(result[1])
    return uuid.UUID(payload["run_id"])


async def enqueue_sync_run(pipeline_id: uuid.UUID) -> None:
    settings = get_settings()
    client = await get_redis()
    await client.lpush(
        settings.sync_queue,
        json.dumps({"pipeline_id": str(pipeline_id)}),
    )


async def dequeue_sync_run(timeout: int = 5) -> uuid.UUID | None:
    settings = get_settings()
    client = await get_redis()
    try:
        result = await client.brpop(settings.sync_queue, timeout=timeout)
    except aioredis.TimeoutError:
        return None
    if not result:
        return None
    payload = json.loads(result[1])
    return uuid.UUID(payload["pipeline_id"])


async def enqueue_pathway_sync(source_id: uuid.UUID) -> None:
    """Enqueue a pathway sync job for a specific source."""
    settings = get_settings()
    client = await get_redis()
    await client.lpush(settings.pathway_queue, json.dumps({"source_id": str(source_id)}))


async def dequeue_pathway_sync(timeout: int = 5) -> uuid.UUID | None:
    """Dequeue a pathway sync job (blocking, returns None on timeout)."""
    settings = get_settings()
    client = await get_redis()
    try:
        result = await client.brpop(settings.pathway_queue, timeout=timeout)
    except aioredis.TimeoutError:
        return None
    if not result:
        return None
    payload = json.loads(result[1])
    return uuid.UUID(payload["source_id"])
