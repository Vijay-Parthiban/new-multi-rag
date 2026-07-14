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
        db_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=db_root,
        check=False,
    )
    raise SystemExit(result.returncode)
