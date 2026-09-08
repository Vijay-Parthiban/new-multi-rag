from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_shared.types import SearchMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    docker_network: str = "rag-shared"

    database_url: str = "postgresql+psycopg://crawler:crawler@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"
    rq_default_timeout: int = 3600
    rq_eval_queue: str = "eval"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = "qdrant"
    qdrant_collection: str = "scrape_embeddings"

    litellm_base_url: str = "http://host.docker.internal:4000"
    openai_api_key: str = "sk-bot"
    # LiteLLM embedding models — must match web-scrapper-workspace ingest settings
    embedding_model: str = "nvidia-embed-passage"
    sparse_embedding_model: str = "Qdrant/bm25"
    default_retrieval_mode: SearchMode = SearchMode.HYBRID
    retrieve_limit: int = 20

    reranker_enabled: bool = True
    reranker_model: str = "nvidia-rerank"
    rerank_top_k: int = 5

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
