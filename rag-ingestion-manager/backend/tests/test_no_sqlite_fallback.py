"""init_db must not invent a database when the configured one is down.

The app used to catch a failed Postgres connection in init_db and switch the whole
process to storage/ingestion.db. It then served whatever stale rows that file held for
as long as it stayed up. Those rows named a Qdrant collection written by a different
embedding model, so every chat query died on vector dimensions and the error pointed at
Qdrant instead of at the database. These tests pin the loud failure.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.shared.db import session


class _FailingEngine:
    """A Postgres engine whose server is not up. begin() raises before the context opens."""

    def begin(self):
        raise OSError("connection refused")

    async def dispose(self) -> None:
        return None


def _postgres_settings(storage: Path) -> SimpleNamespace:
    return SimpleNamespace(
        async_database_url="postgresql+asyncpg://ingestion:ingestion@postgres:5432/ingestion",
        storage_path=str(storage),
    )


def test_init_db_raises_instead_of_falling_back(tmp_path, monkeypatch):
    """The failure reaches the caller, so the app cannot start on the wrong database."""
    monkeypatch.setattr(session, "get_settings", lambda: _postgres_settings(tmp_path))
    monkeypatch.setattr(session, "_engine", _FailingEngine(), raising=False)
    monkeypatch.setattr(session, "_session_factory", None, raising=False)

    with pytest.raises(OSError, match="connection refused"):
        asyncio.run(session.init_db())


def test_init_db_creates_no_sqlite_file(tmp_path, monkeypatch):
    """The old fallback wrote storage/ingestion.db. Nothing may write it now."""
    monkeypatch.setattr(session, "get_settings", lambda: _postgres_settings(tmp_path))
    monkeypatch.setattr(session, "_engine", _FailingEngine(), raising=False)
    monkeypatch.setattr(session, "_session_factory", None, raising=False)

    with pytest.raises(OSError):
        asyncio.run(session.init_db())

    assert list(tmp_path.glob("*.db")) == []
