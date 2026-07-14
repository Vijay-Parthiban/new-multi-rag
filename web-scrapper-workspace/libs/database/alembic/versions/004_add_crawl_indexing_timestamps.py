"""Track markdown and image vector indexing completion per crawl job.

Revision ID: 004
Revises: 003
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_jobs",
        sa.Column("markdown_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("image_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawl_jobs", "image_indexed_at")
    op.drop_column("crawl_jobs", "markdown_indexed_at")
