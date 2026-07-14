"""Add embedding_source to scrape_jobs.

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_jobs",
        sa.Column("embedding_source", sa.String(length=20), nullable=False, server_default="markdown"),
    )


def downgrade() -> None:
    op.drop_column("scrape_jobs", "embedding_source")
