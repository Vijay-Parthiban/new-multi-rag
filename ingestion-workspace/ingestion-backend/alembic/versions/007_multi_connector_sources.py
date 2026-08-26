"""Add source_connectors table, connector/pipeline monitor modes on sources, per-link PipelineSource config.

This migration:
1. Creates source_connectors table for multi-connector-per-source support
2. Adds connector_monitor_mode, connector_sync_interval_minutes,
   pipeline_monitor_mode, pipeline_sync_interval_minutes to sources
3. Makes sources.connector_type nullable (now optional, connectors are in source_connectors)
4. Adds monitor_mode and sync_interval_minutes to pipeline_sources M2M
5. Migrates existing single-connector sources into source_connectors rows

Revision ID: 007_multi_connector_sources
Revises: 006_source_indexed_files
Create Date: 2026-08-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "007_multi_connector_sources"
down_revision: Union[str, None] = "006_source_indexed_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create source_connectors table
    op.create_table(
        "source_connectors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "monitor_mode",
            postgresql.ENUM("live", "scheduled", name="source_monitor_mode", create_type=False),
            nullable=False,
            server_default="live",
        ),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disconnected"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_connectors_source_id", "source_connectors", ["source_id"])

    # 2. Add connector/pipeline monitor mode columns to sources
    op.add_column(
        "sources",
        sa.Column(
            "connector_monitor_mode",
            postgresql.ENUM("live", "scheduled", name="source_monitor_mode", create_type=False),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "sources",
        sa.Column("connector_sync_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column(
            "pipeline_monitor_mode",
            postgresql.ENUM("live", "scheduled", name="source_monitor_mode", create_type=False),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "sources",
        sa.Column("pipeline_sync_interval_minutes", sa.Integer(), nullable=True),
    )

    # Copy existing monitor_mode → connector_monitor_mode for existing rows
    op.execute(
        "UPDATE sources SET connector_monitor_mode = monitor_mode, "
        "connector_sync_interval_minutes = sync_interval_minutes"
    )

    # Make connector_type nullable (multi-connector sources won't set it)
    op.alter_column("sources", "connector_type", existing_type=sa.String(64), nullable=True)

    # 3. Add monitor config to pipeline_sources M2M
    op.add_column(
        "pipeline_sources",
        sa.Column(
            "monitor_mode",
            postgresql.ENUM("live", "scheduled", name="source_monitor_mode", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "pipeline_sources",
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=True),
    )

    # 4. Migrate existing single-connector sources into source_connectors
    # This creates a SourceConnector row for each existing source that has connector_type set
    op.execute("""
        INSERT INTO source_connectors (id, source_id, connector_type, config, monitor_mode,
                                       sync_interval_minutes, enabled, last_sync_at, status,
                                       error_message, created_at, updated_at)
        SELECT gen_random_uuid(), id, connector_type, config, monitor_mode,
               sync_interval_minutes, enabled, last_sync_at, status,
               error_message, created_at, updated_at
        FROM sources
        WHERE connector_type IS NOT NULL AND connector_type != ''
    """)


def downgrade() -> None:
    op.drop_column("pipeline_sources", "sync_interval_minutes")
    op.drop_column("pipeline_sources", "monitor_mode")
    op.alter_column("sources", "connector_type", existing_type=sa.String(64), nullable=False)
    op.drop_column("sources", "pipeline_sync_interval_minutes")
    op.drop_column("sources", "pipeline_monitor_mode")
    op.drop_column("sources", "connector_sync_interval_minutes")
    op.drop_column("sources", "connector_monitor_mode")
    op.drop_index("ix_source_connectors_source_id", table_name="source_connectors")
    op.drop_table("source_connectors")
