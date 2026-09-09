"""Add knowledge_profile_id column to pipelines table.

Revision ID: 009_pipeline_knowledge_profile
Revises: 008_knowledge_store
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "009_pipeline_knowledge_profile"
down_revision: Union[str, None] = "008_knowledge_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipelines",
        sa.Column(
            "knowledge_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("pipelines", "knowledge_profile_id")
