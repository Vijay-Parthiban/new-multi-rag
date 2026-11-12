"""The transcript a multi-turn run produced.

Revision ID: 015
Revises: 014
Create Date: 2026-11-06

A multi-turn row replays its user turns and keeps only the last answer for scoring. The
turns the pipeline actually answered were thrown away, so a run could not be audited and a
conversation metric had nothing to read. This column stores that transcript as
`[{role, content}, ...]`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "evaluation_run_items" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("evaluation_run_items")}
    if "generated_turns" not in columns:
        op.add_column(
            "evaluation_run_items",
            sa.Column("generated_turns", postgresql.JSONB(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "evaluation_run_items" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("evaluation_run_items")}
    if "generated_turns" in columns:
        op.drop_column("evaluation_run_items", "generated_turns")
