"""Add the retrieval settings an assistant pipeline owns

Revision ID: 017_pipeline_retrieval_settings
Revises: 016_chunk_config_page_images
Create Date: 2026-10-09

The pipeline form used to offer no retrieval settings, so every assistant turn
took the deployment's: how many chunks the search returns, whether a reranker
reorders them, and how many reranked chunks reach the answering model. The three
belong to the pipeline, next to its chat model and sampling settings, so one
pipeline can retrieve widely without reranking and another can rerank narrowly.

``retrieve_limit`` and ``rerank_top_k`` are ``top_k`` in different places: the
first is what the search returns, the second is what survives reranking. A
disabled reranker ignores the second one, and every retrieved chunk then reaches
the model.

Every pipeline created before this migration takes the deployment's values, which
are the ones it already ran with. The columns are NOT NULL with a server default,
so an existing row is backfilled by the same statement that adds the column.

PostgreSQL only: ``Base.metadata.create_all`` never alters an existing table, and
SQLite is patched by ``_ensure_sqlite_columns`` in ``src/shared/db/session.py``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "017_pipeline_retrieval_settings"
down_revision: Union[str, None] = "016_chunk_config_page_images"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column, type). The types match the SQLAlchemy model.
_ADDED = (
    ("retrieve_limit", "INTEGER NOT NULL DEFAULT 20"),
    ("rerank_enabled", "BOOLEAN NOT NULL DEFAULT true"),
    ("rerank_top_k", "INTEGER NOT NULL DEFAULT 5"),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for column, column_type in _ADDED:
        op.execute(f"ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS {column} {column_type}")


def downgrade() -> None:
    if not _is_postgres():
        return
    for column, _ in _ADDED:
        op.execute(f"ALTER TABLE pipelines DROP COLUMN IF EXISTS {column}")
