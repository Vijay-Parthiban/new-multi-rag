"""Add the model columns that no earlier migration created

Revision ID: 014_missing_model_columns
Revises: 013_assistant_reasoning_patterns
Create Date: 2026-09-29

Six columns exist in ``src/shared/db/models.py`` and in no migration before this
one. ``Base.metadata.create_all`` never adds a column to a table that already
exists, so a PostgreSQL database built from the migration chain alone lacked
them and every query that selected one failed:

    ProgrammingError: column sources.connector_sync_interval_seconds does not exist

That made the documented container path, ``docker compose up -d``, produce an API
that could not serve ``GET /api/sources`` on a fresh volume.

``IF NOT EXISTS`` makes this migration safe on a database that already has the
columns, which is why every live volume can take it with no repair step. An
existing installation that was created by ``create_all`` already has all six.

SQLite is skipped. ``init_db`` in ``src/shared/db/session.py`` patches that
dialect through ``_ensure_sqlite_columns``, and SQLite has no
``ADD COLUMN IF NOT EXISTS`` to make this idempotent.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014_missing_model_columns"
down_revision: Union[str, None] = "013_assistant_reasoning_patterns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, type). The type matches the SQLAlchemy model.
_COLUMNS = (
    ("knowledge_products", "ingestion_profile_id", "VARCHAR(36)"),
    ("knowledge_products", "pipeline_fingerprint", "VARCHAR(64)"),
    ("sources", "total_files", "INTEGER DEFAULT 0"),
    ("sources", "total_size_bytes", "INTEGER DEFAULT 0"),
    ("sources", "connector_sync_interval_seconds", "INTEGER"),
    ("source_connectors", "sync_interval_seconds", "INTEGER"),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for table, column, column_type in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_type}"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table, column, _ in _COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
