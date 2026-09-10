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
    engine = _get_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        print(f"PostgreSQL connection failed ({e}). Falling back to SQLite database...")
        global _engine, _session_factory
        if _engine is not None:
            await _engine.dispose()
        settings = get_settings()
        db_dir = Path(settings.storage_path)
        db_dir.mkdir(parents=True, exist_ok=True)
        sqlite_path = db_dir / "ingestion.db"
        sqlite_url = f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"
        _engine = create_async_engine(sqlite_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            _ensure_sqlite_columns(sqlite_path)

def _ensure_sqlite_columns(sqlite_path) -> None:
    import sqlite3
    try:
        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()
        for col_def in [
            "total_files INTEGER DEFAULT 0",
            "total_size_bytes INTEGER DEFAULT 0",
            "error_message TEXT",
        ]:
            try:
                cur.execute(f"ALTER TABLE sources ADD COLUMN {col_def}")
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception:
        pass
