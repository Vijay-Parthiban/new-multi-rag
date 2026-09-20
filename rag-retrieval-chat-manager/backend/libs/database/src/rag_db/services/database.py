from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag_shared.config import Settings, get_settings


@lru_cache(maxsize=None)
def _engine_for_url(url: str):
    """One engine per database URL, for the life of the process.

    Building the engine per call opened a fresh pool on every request and leaked
    the old one, so the app drained Postgres ``max_connections`` and then failed
    with "remaining connection slots are reserved for roles with the SUPERUSER
    attribute".
    """
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    return _engine_for_url(settings.database_url)


def get_session_factory(settings: Settings | None = None):
    engine = get_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
