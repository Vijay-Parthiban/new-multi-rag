import asyncio
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_MAX_ATTEMPTS = 30
_RETRY_SECONDS = 2


def _alembic_config() -> Config:
    return Config(str(_BACKEND_ROOT / "alembic.ini"))


def upgrade_head() -> None:
    command.upgrade(_alembic_config(), "head")


def main() -> None:
    """Run Alembic migrations to head (used by docker compose migrate service)."""
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            upgrade_head()
            return
        except Exception as exc:
            last_error = exc
            if attempt == _MAX_ATTEMPTS:
                break
            time.sleep(_RETRY_SECONDS)
    print(f"Database migrations failed after {_MAX_ATTEMPTS} attempts: {last_error}", file=sys.stderr)
    raise SystemExit(1) from last_error


async def run_migrations() -> None:
    """Legacy async entrypoint — prefer `main()` via compose migrate service."""
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(upgrade_head)
            return
        except Exception as exc:
            last_error = exc
            if attempt == _MAX_ATTEMPTS:
                break
            await asyncio.sleep(_RETRY_SECONDS)
    raise RuntimeError("Database migrations failed after retries.") from last_error


if __name__ == "__main__":
    main()
