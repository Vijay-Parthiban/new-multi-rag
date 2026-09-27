"""Assistant reasoning patterns

Revision ID: 013_assistant_reasoning_patterns
Revises: 012_pipeline_model_settings
Create Date: 2026-09-27

SQL search (`relational`) is retired as an assistant strategy and two reasoning
patterns replace it: `self_rag`, which grades each retrieved passage and then
checks the answer is grounded in those passages, and `corrective`, which answers
only from the passages that grade well and abstains otherwise.

Both are assistant strategies, so they belong on the same enum the assistant
values already use.

PostgreSQL keeps a value in an enum type that nothing references, and dropping one
would fail while any row used it, so `relational` stays on the type. Nothing can
reach it: the request schema no longer accepts it and the retriever no longer
dispatches it.

SQLite stores an Enum as VARCHAR, so there is no type to extend there and the
labels are added only on PostgreSQL, exactly as migration 011 does it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_assistant_reasoning_patterns"
down_revision: Union[str, None] = "012_pipeline_model_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_STRATEGIES = ("self_rag", "corrective")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        for value in _NEW_STRATEGIES:
            op.execute(sa.text(f"ALTER TYPE rag_strategy ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type, so the two labels stay.
    # Leaving them is harmless: an unused label is not selectable.
    pass
