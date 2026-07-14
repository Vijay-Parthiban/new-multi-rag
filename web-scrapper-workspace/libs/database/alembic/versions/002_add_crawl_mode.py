"""Add crawl_mode column to crawl_jobs.

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_jobs",
        sa.Column("crawl_mode", sa.String(length=20), nullable=False, server_default="httpx"),
    )


def downgrade() -> None:
    op.drop_column("crawl_jobs", "crawl_mode")
