from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://crawler:crawler@localhost:5432/crawler"
    redis_url: str = "redis://localhost:6379/0"

    @property
    def async_database_url(self) -> str:
        """psycopg v3 natively supports async; same URL works with create_async_engine."""
        return self.database_url
    crawl_data_dir: Path = Path("./data/crawls")
    scrape_data_dir: Path = Path("./data/scrapes")
    rq_default_timeout: int = 3600

    api_base_url: str = "http://localhost:8000"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "scrape_embeddings"
    litellm_base_url: str = "http://host.docker.internal:4000"
    openai_api_key: str = "sk-bot"
    # LiteLLM embedding model — must match rag-app-workspace EMBEDDING_MODEL
    embedding_model: str = "nvidia-embed-passage"
    sparse_embedding_model: str = "Qdrant/bm25"
    playwright_timeout_ms: int = 30000
    scrape_concurrency: int = 3
    scrape_io_workers: int = 4
    scrape_embed_workers: int = 4
    scrape_max_retries: int = 3
    api_key: str = ""
    # When true, seed URLs may target private/loopback hosts (local/dev only).
    allow_private_crawl_urls: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
