from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag_shared.config import Settings, get_settings


def get_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session_factory(settings: Settings | None = None):
    engine = get_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
