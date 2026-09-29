from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_shared.types import SearchMode

# The env files are resolved against the backend directory, not the working directory.
# `env_file=".env"` is a relative path, so it only worked when the process happened to
# start in `backend/`. `rag-db-migrate` runs alembic with cwd=libs/database, where no
# `.env` exists, so it fell back to the container hostname and failed to resolve
# `postgres` on a host run. A container never showed this because compose injects the
# values as real environment variables.
_BACKEND_DIR = Path(__file__).resolve().parents[4]
_ENV_FILES = (str(_BACKEND_DIR / ".env"), str(_BACKEND_DIR / ".env.local"))


class Settings(BaseSettings):
    # `.env` holds the container hostnames and is what the retrieval compose reads.
    # `.env.local` is an optional host-run override and is gitignored. pydantic-settings
    # gives the later file precedence, so a key in `.env.local` wins over the same key in
    # `.env`. A real environment variable still beats both.
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    docker_network: str = "rag-shared"

    database_url: str = "postgresql+psycopg://crawler:crawler@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"
    rq_default_timeout: int = 3600
    rq_eval_queue: str = "eval"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = "qdrant"
    qdrant_collection: str = "scrape_embeddings"
    # The ingestion fanout writes knowledge-product collections to its own Qdrant.
    qdrant_kp_url: str = ""

    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str = ""
    opensearch_password: str = ""

    ingestion_service_url: str = "http://localhost:8007"
    ingestion_database_url: str = "postgresql://ingestion:ingestion@localhost:5432/ingestion"

    guardrails_url: str = "http://localhost:18000"
    # The LLM-backed validators need about a second each, so the round trip needs more than
    # a couple of seconds.
    guardrails_timeout_s: float = 15.0
    # Bundled guardrails golden dataset, resolved against the process working directory.
    # The service also looks in ../golden and ../../golden before it gives up.
    guardrails_golden_dataset_path: str = "../../golden/guardrails-dataset.json"

    litellm_base_url: str = "http://host.docker.internal:4000"
    openai_api_key: str = "sk-bot"
    # LiteLLM embedding models — must match web-scrapper-workspace ingest settings
    embedding_model: str = "nvidia-embed-textonly"
    sparse_embedding_model: str = "Qdrant/bm25"
    default_retrieval_mode: SearchMode = SearchMode.HYBRID
    retrieve_limit: int = 20

    reranker_enabled: bool = True
    reranker_model: str = "nvidia-rerank"
    rerank_top_k: int = 5

    # The score a passage must reach to survive the relevance grader that the
    # self-reflective and corrective strategies run. Below it a passage is dropped;
    # when none reach it the corrective pattern abstains rather than answering from
    # nothing. 0.5 sits at the midpoint of the grader's 0 to 1 scale.
    relevance_threshold: float = 0.5

    chat_model: str = "llama-3.3-70b-versatile"
    vision_model: str = "groq-vision"
    fusion_model: str = "llama-3.3-70b-versatile"
    chat_max_tokens: int = 1024
    chat_temperature: float = 0.2

    ragas_judge_model: str = "llama-3.3-70b-versatile"
    ragas_enabled: bool = True
    chat_metrics_async: bool = True

    eval_worker_concurrency: int = 2
    eval_default_k: int = 5

    api_host: str = "0.0.0.0"
    api_port: int = 8001
    api_key: str = ""

    # OpenTelemetry. These live here rather than only in the process environment because
    # pydantic-settings loads `.env` into this object and does **not** populate
    # `os.environ`. `init_tracing` read them from `os.getenv`, so a value in `.env` or
    # `.env.local` never reached it and the host run kept exporting to the container
    # hostname `otel` on every request.
    otel_tracing_enabled: bool = True
    otel_service_name: str = "rag-platform"
    otel_exporter_otlp_endpoint: str = "http://otel:4318"
    otel_console_export: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
