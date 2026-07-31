from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database for reading Source/Pipeline configs
    database_url: str = "postgresql://ingestion:ingestion@localhost:5432/ingestion"

    # MinIO / S3-compatible storage
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_use_ssl: str = "false"
    minio_bucket_prefix: str = "source"

    # Redis queue for triggering RAG re-index
    redis_url: str = "redis://localhost:6379/0"
    sync_queue: str = "ingestion:sync:jobs"

    # Polling interval for checking new/changed sources (seconds)
    source_poll_interval_sec: int = 60

    # Max concurrent connector syncs
    max_concurrent_syncs: int = 4

    # Pathway connector output directory (within container)
    connector_output_dir: str = "/tmp/pathway-output"

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