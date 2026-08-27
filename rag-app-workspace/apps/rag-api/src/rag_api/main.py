from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rag_core import RAGPipeline
from rag_shared.auth import verify_api_key
from rag_shared.config import Settings, get_settings
from rag_shared.logging_config import setup_logging
from redis import Redis
from rq import Queue
from retrieval_core import Retriever
from generation_core import Generator
from rag_api.routes import (
    chat,
    evaluate,
    generate,
    guardrails,
    guardrails_evaluate,
    health,
    prompts,
    rerank,
    retrieve,
    search,
)


@lru_cache
def _cached_settings() -> Settings:
    return get_settings()


def get_redis_queue(settings: Settings | None = None) -> Queue:
    settings = settings or _cached_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue(settings.rq_eval_queue, connection=redis_conn, default_timeout=settings.rq_default_timeout)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from rag_shared.tracing import init_tracing
    init_tracing()

    setup_logging()
    settings = _cached_settings()
    app.state.settings = settings
    app.state.pipeline = RAGPipeline(settings)
    app.state.retriever = Retriever(settings)
    app.state.generator = Generator(settings)
    app.state.queue = get_redis_queue(settings)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Platform API", 
        version="0.1.0", 
        lifespan=lifespan,
        dependencies=[Depends(verify_api_key)]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(retrieve.router)
    app.include_router(rerank.router)
    app.include_router(generate.router)
    app.include_router(chat.router)
    app.include_router(evaluate.router)
    app.include_router(prompts.router)
    app.include_router(guardrails.router)
    app.include_router(guardrails_evaluate.router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = _cached_settings()
    uvicorn.run("rag_api.main:app", host=settings.api_host, port=settings.api_port, reload=False)
