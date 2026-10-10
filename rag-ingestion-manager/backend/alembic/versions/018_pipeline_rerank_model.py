"""Add the reranker model an assistant pipeline selects

Revision ID: 018_pipeline_rerank_model
Revises: 017_pipeline_retrieval_settings
Create Date: 2026-10-09

The pipeline already decided whether a reranker runs and how many chunks survive
it. Which reranker was the deployment's alone, so every pipeline in a deployment
reordered with the same model. The pipeline now names it, and the form offers the
models the LiteLLM proxy reports with mode ``rerank``.

Nullable, and a null means the retrieval manager's own ``reranker_model`` applies.
That is what every row written before this column gets, so nothing changes for an
existing pipeline.

PostgreSQL only: ``Base.metadata.create_all`` never alters an existing table, and
SQLite is patched by ``_ensure_sqlite_columns`` in ``src/shared/db/session.py``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "018_pipeline_rerank_model"
down_revision: Union[str, None] = "017_pipeline_retrieval_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMN = ("rerank_model", "VARCHAR(128)")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    column, column_type = _COLUMN
    op.execute(f"ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS {column} {column_type}")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE pipelines DROP COLUMN IF EXISTS {_COLUMN[0]}")
