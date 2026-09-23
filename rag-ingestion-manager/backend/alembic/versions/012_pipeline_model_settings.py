"""Pipeline model settings

Revision ID: 012_pipeline_model_settings
Revises: 011_assistant_pipeline
Create Date: 2026-09-22

An assistant pipeline can now carry sampling settings for its answering call:
temperature, top_p, sampler top_k and max_tokens. They are stored as one JSON
document rather than a column each, because the set is small and providers keep
changing which of them are honoured.

Nullable on purpose. A null means the retrieval manager's service defaults
apply, which is exactly how every pipeline behaved before this column existed.

Note for readers of the SQLAlchemy model: ``PipelineConfig.top_k`` on the
retrieval side is how many reranked chunks reach the prompt. The ``top_k``
inside this document is the sampler's cutoff. They are unrelated.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "012_pipeline_model_settings"
down_revision: Union[str, None] = "011_assistant_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("model_settings", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "model_settings")
