"""Add knowledge_profiles, knowledge_profile_sources, and knowledge_destination_configs tables.

Revision ID: 008_knowledge_store
Revises: 007_multi_connector_sources
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "008_knowledge_store"
down_revision: Union[str, None] = "007_multi_connector_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create knowledge_profiles table
    op.create_table(
        "knowledge_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_profiles_name", "knowledge_profiles", ["name"], unique=True)

    # 2. Create knowledge_profile_sources M2M table
    op.create_table(
        "knowledge_profile_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_knowledge_profile_sources_unique",
        "knowledge_profile_sources",
        ["knowledge_profile_id", "source_id"],
        unique=True,
    )

    # 3. Create knowledge_destination_configs table
    op.create_table(
        "knowledge_destination_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("destination_type", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_knowledge_dest_profile_type_unique",
        "knowledge_destination_configs",
        ["knowledge_profile_id", "destination_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("knowledge_destination_configs")
    op.drop_table("knowledge_profile_sources")
    op.drop_table("knowledge_profiles")
