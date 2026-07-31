from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://ingestion:ingestion@localhost:5432/ingestion"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: str = "./storage"
    file_manager_queue: str = "file_manager:jobs"
    pipeline_queue: str = "ingestion:pipeline:jobs"
    sync_queue: str = "ingestion:sync:jobs"
    pathway_queue: str = "pathway:sync:jobs"
    chunk_size_bytes: int = 5 * 1024 * 1024  # 5 MB reference for clients

    # Vector / embedding (shared with web-scrapper RAG stack)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = "qdrant"
    qdrant_collection: str = "scrape_embeddings"
    litellm_base_url: str = "http://host.docker.internal:4000"
    openai_api_key: str = "sk-bot"
    embedding_model: str = "nvidia-embed-passage"
    multimodal_embedding_model: str = "nvidia-embed-passage"
    sparse_embedding_model: str = "Qdrant/bm25"
    embed_workers: int = 4

    # Cron schedule for pipeline file sync (APScheduler CronTrigger fields)
    sync_cron_year: str = "*"
    sync_cron_month: str = "*"
    sync_cron_day: str = "*"
    sync_cron_week: str = "*"
    sync_cron_dow: str = "*"       # day_of_week: mon-sun or 0-6
    sync_cron_hour: str = "*"
    sync_cron_minute: str = "*/10"
    sync_cron_second: str = "0"

    # MinIO Object Storage
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_use_ssl: str = "false"
    minio_bucket_prefix: str = "source"

    # Web scrapper API (crawl-scrape pipeline)
    scraper_api_url: str = "http://localhost:8000"
    scraper_api_key: str = ""
    api_key: str = ""

    @property
    def embedding_model_options(self) -> list[str]:
        return [
            self.embedding_model,
            self.multimodal_embedding_model,
            "text-embedding-3-small",
            "text-embedding-3-large",
        ]

    @property
    def unique_embedding_models(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for m in self.embedding_model_options:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if "+asyncpg" in url:
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
