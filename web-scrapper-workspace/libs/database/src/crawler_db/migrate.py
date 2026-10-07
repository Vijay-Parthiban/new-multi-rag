import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run Alembic migrations to `head`.

    This command needs to run with the working directory set to the Alembic project
    root (the directory that contains `alembic.ini` and the `alembic/` folder).

    In development that is typically `libs/database/`.
    In Docker we copy these files into `/app/libs/database/`.
    """
    docker_db_root = Path("/app/libs/database")
    if (docker_db_root / "alembic.ini").exists():
        db_root = docker_db_root
    else:
        # Fallback for local/workspace execution (this file lives at
        # libs/database/src/crawler_db/migrate.py, so parents[2] is libs/database).
        db_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=db_root,
        check=False,
    )
    raise SystemExit(result.returncode)
