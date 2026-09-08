from __future__ import annotations

from redis import Redis
from rq import Worker
from rag_shared.config import get_settings
from rag_shared.logging_config import setup_logging


def run() -> None:
    from rag_shared.tracing import init_tracing
    init_tracing()
    
    setup_logging()
    settings = get_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    worker = Worker([settings.rq_eval_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    run()
