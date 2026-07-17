from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler_shared.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    """Return (and lazily initialize) the SQLAlchemy engine.

    Why lazy init:
    - Allows import-time module loading in API/worker without creating connections immediately.
    - Makes tests able to override engine/session patterns when needed.
    """
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager providing a transactional session.

    Commits on success, rolls back on exception.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("db_session_rollback")
        raise
    finally:
        session.close()


# ── Async session support ──────────────────────────────────────────

def _get_async_engine() -> AsyncEngine:
    """Lazily create the async engine on first use."""
    global _async_engine, _AsyncSessionLocal
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
        _AsyncSessionLocal = async_sessionmaker(_async_engine, expire_on_commit=False)
    return _async_engine


def AsyncSessionLocal() -> AsyncSession:
    """Return a new async session, creating the engine lazily if needed."""
    _get_async_engine()
    assert _AsyncSessionLocal is not None
    return _AsyncSessionLocal()


async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing a transactional session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("async_db_session_rollback")
            raise


async def close_async_db() -> None:
    global _async_engine, _AsyncSessionLocal
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _AsyncSessionLocal = None

