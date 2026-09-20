from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Lazily create the async engine on first use (avoids DNS failures at import time)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.async_database_url
        if "sqlite" in url:
            _engine = create_async_engine(url, pool_pre_ping=True)
        else:
            _engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=30,
                max_overflow=50,
                pool_timeout=30,
            )
    return _engine


def AsyncSessionLocal() -> AsyncSession:
    """Return a new async session, creating the engine lazily if needed."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def init_db() -> None:
    from pathlib import Path
    from src.shared.db.models import Base
    settings = get_settings()
    engine = _get_engine()

    if "sqlite" in settings.async_database_url:
        # create_all never renames a table and never adds a column, so do both
        # around it. The rename must run first: if create_all runs first it
        # makes an empty knowledge_products, the rename then fails, and the old
        # table keeps the rows.
        db_path = Path(settings.async_database_url.split("///", 1)[-1])
        _ensure_sqlite_renames(db_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _ensure_sqlite_columns(db_path)
        return

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        print(f"PostgreSQL connection failed ({e}). Falling back to SQLite database...")
        global _engine, _session_factory
        if _engine is not None:
            await _engine.dispose()
        db_dir = Path(settings.storage_path)
        db_dir.mkdir(parents=True, exist_ok=True)
        sqlite_path = db_dir / "ingestion.db"
        sqlite_url = f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"
        _engine = create_async_engine(sqlite_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _ensure_sqlite_renames(sqlite_path)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _ensure_sqlite_columns(sqlite_path)
        return


def _ensure_sqlite_renames(sqlite_path) -> None:
    """Rename the knowledge-profile tables and indexes on an existing SQLite file.

    Idempotent: every statement fails harmlessly once it has already run.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()
        for statement in [
            "ALTER TABLE knowledge_profiles RENAME TO knowledge_products",
            "ALTER TABLE knowledge_profile_sources RENAME TO knowledge_product_sources",
            "ALTER TABLE knowledge_destination_configs RENAME TO knowledge_product_destinations",
            "ALTER TABLE knowledge_product_sources RENAME COLUMN knowledge_profile_id TO knowledge_product_id",
            "ALTER TABLE knowledge_product_destinations RENAME COLUMN knowledge_profile_id TO knowledge_product_id",
            "ALTER TABLE pipelines RENAME COLUMN knowledge_profile_id TO knowledge_product_id",
            "DROP INDEX IF EXISTS ix_knowledge_profile_sources_unique",
            "DROP INDEX IF EXISTS ix_knowledge_dest_profile_type_unique",
            "DROP INDEX IF EXISTS ix_knowledge_products_name",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_knowledge_products_name ON knowledge_products (name)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_knowledge_product_sources_unique "
            "ON knowledge_product_sources (knowledge_product_id, source_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_knowledge_product_dest_type_unique "
            "ON knowledge_product_destinations (knowledge_product_id, destination_type)",
            "DELETE FROM knowledge_product_destinations WHERE destination_type = 'graph_neo4j'",
            "DELETE FROM indexed_files WHERE pipeline_id IS NULL",
        ]:
            try:
                cur.execute(statement)
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass


def _ensure_sqlite_columns(sqlite_path) -> None:
    import sqlite3
    try:
        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()
        for table, col_def in [
            ("sources", "total_files INTEGER DEFAULT 0"),
            ("sources", "total_size_bytes INTEGER DEFAULT 0"),
            ("sources", "error_message TEXT"),
            ("sources", "connector_sync_interval_seconds INTEGER"),
            ("source_connectors", "sync_interval_seconds INTEGER"),
            ("knowledge_products", "monitor_mode TEXT DEFAULT 'scheduled'"),
            ("knowledge_products", "sync_interval_seconds INTEGER"),
            ("knowledge_products", "sync_interval_minutes INTEGER"),
            ("knowledge_products", "ingestion_profile_id VARCHAR(36)"),
            ("knowledge_products", "pipeline_fingerprint VARCHAR(64)"),
            ("ingestion_profiles", "modality_mode TEXT DEFAULT 'text'"),
            ("ingestion_profiles", "text_embedding_model TEXT DEFAULT 'nvidia-embed-textonly'"),
            ("ingestion_profiles", "caption_model TEXT"),
            ("ingestion_profiles", "image_min_pixels INTEGER DEFAULT 10000"),
        ]:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass
