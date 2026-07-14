from functools import lru_cache

import redis

from crawler_shared.config import get_settings


@lru_cache
def get_redis_connection() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url)
