"""Add sources and pipeline_sources tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005_sources"
down_revision: Union[str, None] = "004_indexed_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # source_monitor_mode enum
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "monitor_mode",
            sa.Enum("live", "scheduled", name="source_monitor_mode"),
            nullable=False,
            server_default="live",
        ),
        sa.Column("minio_bucket", sa.String(length=256), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_name"), "sources", ["name"], unique=True)
    op.create_index(op.f("ix_sources_minio_bucket"), "sources", ["minio_bucket"], unique=True)

    # pipeline_sources M2M join
    op.create_table(
        "pipeline_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pipeline_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_sources_unique",
        "pipeline_sources",
        ["pipeline_id", "source_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_sources_unique", table_name="pipeline_sources")
    op.drop_table("pipeline_sources")
    op.drop_index(op.name("ix_sources_minio_bucket"), table_name="sources")
    op.drop_index(op.name("ix_sources_name"), table_name="sources")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS source_monitor_mode")