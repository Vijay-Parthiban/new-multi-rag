"""Per-pipeline Qdrant and embedding config on scrape jobs.

Revision ID: 005
Revises: 004
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_jobs",
        sa.Column("qdrant_collection", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column("sparse_embedding_model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column("pipeline_description", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "scrape_jobs",
        sa.Column("use_sparse", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("scrape_jobs", "use_sparse")
    op.drop_column("scrape_jobs", "pipeline_description")
    op.drop_column("scrape_jobs", "sparse_embedding_model")
    op.drop_column("scrape_jobs", "embedding_model")
    op.drop_column("scrape_jobs", "qdrant_collection")
