"""Add the per-source webscraping columns

Revision ID: 015_source_webscrape
Revises: 014_missing_model_columns
Create Date: 2026-09-30

``Source`` gains three columns that drive the per-source webscrape feature: a
switch plus the crawl depth and page cap for one `*_scrp.txt` manifest.

``Base.metadata.create_all`` never adds a column to a table that already exists,
so a database built from the migration chain alone needs them here. PostgreSQL
only: ``IF NOT EXISTS`` makes the statement safe on a volume that already has
them. SQLite is patched by ``_ensure_sqlite_columns`` in
``src/shared/db/session.py``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "015_source_webscrape"
down_revision: Union[str, None] = "014_missing_model_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, type). The type matches the SQLAlchemy model.
_COLUMNS = (
    ("sources", "webscrape_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("sources", "webscrape_max_depth", "INTEGER NOT NULL DEFAULT 0"),
    ("sources", "webscrape_max_pages", "INTEGER NOT NULL DEFAULT 50"),
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
