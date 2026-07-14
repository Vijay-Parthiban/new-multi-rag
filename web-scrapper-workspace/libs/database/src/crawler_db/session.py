from collections.abc import Generator
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler_shared.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


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
