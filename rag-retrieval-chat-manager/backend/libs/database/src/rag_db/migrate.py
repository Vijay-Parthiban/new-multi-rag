from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run Alembic migrations to head."""
    docker_db_root = Path("/app/libs/database")
    if (docker_db_root / "alembic.ini").exists():
        db_root = docker_db_root
    else:
        # .../libs/database/src/rag_db/migrate.py -> .../libs/database, which is
        # where alembic.ini lives. parents[1] is .../libs/database/src and holds
        # no config, so alembic reported a missing script_location.
        db_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=db_root,
        check=False,
    )
    raise SystemExit(result.returncode)
