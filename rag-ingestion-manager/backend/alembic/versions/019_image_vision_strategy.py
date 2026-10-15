"""Add image_vision to the rag_strategy enum.

A text-with-images product serves exactly one strategy: it reads the page vectors
the fanout wrote and answers from the page images themselves. The value has to
exist in the enum before a pipeline can select it.

Revision ID: 019_image_vision_strategy
Revises: 018_pipeline_rerank_model
Create Date: 2026-10-15
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_image_vision_strategy"
down_revision: Union[str, None] = "018_pipeline_rerank_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RAG_STRATEGY_TYPE = "rag_strategy"


def upgrade() -> None:
    op.execute(f"ALTER TYPE {_RAG_STRATEGY_TYPE} ADD VALUE IF NOT EXISTS 'image_vision'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum in place. Leaving it costs nothing:
    # no pipeline can select it once the API stops offering it.
    pass
