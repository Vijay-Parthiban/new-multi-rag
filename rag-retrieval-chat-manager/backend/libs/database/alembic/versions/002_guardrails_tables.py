"""Guardrails tables

Revision ID: 002
Revises: 001
Create Date: 2026-09-20

``001_initial_schema`` predates the guardrails models and ``alembic/env.py``
imported only ``chat`` and ``evaluation``, so these six tables were never
created. The guardrails pages failed with "relation does not exist".

The column definitions are taken from ``Base.metadata`` rather than retyped, so
this migration cannot drift from ``rag_db/models/guardrails.py``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Parents first: traces and run items carry foreign keys into these tables.
_TABLES = (
    "guardrails_configs",
    "guardrails_golden_datasets",
    "guardrails_traces",
    "guardrails_golden_dataset_items",
    "guardrails_eval_runs",
    "guardrails_eval_run_items",
)


def _tables():
    from rag_db.models import guardrails  # noqa: F401  (registers the tables)
    from rag_db.models.base import Base

    return Base.metadata


def upgrade() -> None:
    bind = op.get_bind()
    metadata = _tables()
    for name in _TABLES:
        metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    metadata = _tables()
    for name in reversed(_TABLES):
        metadata.tables[name].drop(bind, checkfirst=True)
