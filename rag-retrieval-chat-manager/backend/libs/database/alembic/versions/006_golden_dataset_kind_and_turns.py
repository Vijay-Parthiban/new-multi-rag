"""Conversation turns on a golden dataset

Revision ID: 006
Revises: 005
Create Date: 2026-10-16

A golden dataset could only hold lone questions. Two columns let one hold a
conversation, which is what the multi-turn dataset and the RAGAS and DeepEval
multi-turn formats need.

``golden_datasets.kind``
    "single_turn" or "multi_turn", derived from the rows at import. The
    evaluation page reads it to decide whether the selected pipeline may run the
    dataset: a multi-turn run drives the pipeline's session memory, so a pipeline
    without one cannot run it.

``golden_dataset_items.turns``
    The user turns of one conversation, in order, as a JSON array of
    ``{"role", "content"}`` objects. NULL on a single-turn row. The assistant
    turns stay in ``metadata.expected_turns``, because they are what the
    conversation aimed at and never reach a run.

The server default backfills existing rows with "single_turn", which is what
they are: none of them carries turns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "kind" not in existing:
        op.add_column(
            "golden_datasets",
            sa.Column("kind", sa.String(), nullable=False, server_default="single_turn"),
        )

    existing = {column["name"] for column in inspector.get_columns("golden_dataset_items")}
    if "turns" not in existing:
        op.add_column(
            "golden_dataset_items",
            sa.Column("turns", JSONB(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("golden_dataset_items", "turns")
    op.drop_column("golden_datasets", "kind")
