"""Rename knowledge profile tables to knowledge products and add the fanout ledger.

Revision ID: 010_knowledge_products
Revises: 009_pipeline_knowledge_profile
Create Date: 2026-09-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "010_knowledge_products"
down_revision: Union[str, None] = "009_pipeline_knowledge_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename the three tables. Postgres keeps index names across a table
    #    rename, so the indexes are renamed separately below.
    op.rename_table("knowledge_profiles", "knowledge_products")
    op.rename_table("knowledge_profile_sources", "knowledge_product_sources")
    op.rename_table("knowledge_destination_configs", "knowledge_product_destinations")

    # 2. Rename the foreign key columns.
    op.alter_column(
        "knowledge_product_sources",
        "knowledge_profile_id",
        new_column_name="knowledge_product_id",
    )
    op.alter_column(
        "knowledge_product_destinations",
        "knowledge_profile_id",
        new_column_name="knowledge_product_id",
    )
    op.alter_column("pipelines", "knowledge_profile_id", new_column_name="knowledge_product_id")

    # 3. Rename the indexes.
    op.execute("ALTER INDEX ix_knowledge_profiles_name RENAME TO ix_knowledge_products_name")
    op.execute(
        "ALTER INDEX ix_knowledge_profile_sources_unique "
        "RENAME TO ix_knowledge_product_sources_unique"
    )
    op.execute(
        "ALTER INDEX ix_knowledge_dest_profile_type_unique "
        "RENAME TO ix_knowledge_product_dest_type_unique"
    )

    # 4. Product-level sync schedule.
    op.add_column(
        "knowledge_products",
        sa.Column("monitor_mode", sa.String(16), nullable=False, server_default="scheduled"),
    )
    op.add_column("knowledge_products", sa.Column("sync_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("knowledge_products", sa.Column("sync_interval_minutes", sa.Integer(), nullable=True))

    # 5. The fanout ledger. Replaces the indexed_files rows the fanout used to
    #    write, so two products sharing a bucket keep separate state.
    op.create_table(
        "knowledge_product_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_key", sa.String(1024), nullable=False),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("pages_indexed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("destinations_synced", JSONB, nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_kp_files_unique",
        "knowledge_product_files",
        ["knowledge_product_id", "source_id", "file_key"],
        unique=True,
    )
    op.create_index(
        "ix_kp_files_product_status",
        "knowledge_product_files",
        ["knowledge_product_id", "status"],
    )

    # 6. Neo4j is no longer a destination.
    op.execute("DELETE FROM knowledge_product_destinations WHERE destination_type = 'graph_neo4j'")

    # 7. Drop the fanout's old state rows. pipeline_id IS NULL cannot come from
    #    the pipeline path, which always sets it. The first tick re-indexes.
    op.execute("DELETE FROM indexed_files WHERE pipeline_id IS NULL")


def downgrade() -> None:
    op.drop_table("knowledge_product_files")
    op.drop_column("knowledge_products", "sync_interval_minutes")
    op.drop_column("knowledge_products", "sync_interval_seconds")
    op.drop_column("knowledge_products", "monitor_mode")

    op.execute(
        "ALTER INDEX ix_knowledge_product_dest_type_unique "
        "RENAME TO ix_knowledge_dest_profile_type_unique"
    )
    op.execute(
        "ALTER INDEX ix_knowledge_product_sources_unique "
        "RENAME TO ix_knowledge_profile_sources_unique"
    )
    op.execute("ALTER INDEX ix_knowledge_products_name RENAME TO ix_knowledge_profiles_name")

    op.alter_column("pipelines", "knowledge_product_id", new_column_name="knowledge_profile_id")
    op.alter_column(
        "knowledge_product_destinations",
        "knowledge_product_id",
        new_column_name="knowledge_profile_id",
    )
    op.alter_column(
        "knowledge_product_sources",
        "knowledge_product_id",
        new_column_name="knowledge_profile_id",
    )

    op.rename_table("knowledge_product_destinations", "knowledge_destination_configs")
    op.rename_table("knowledge_product_sources", "knowledge_profile_sources")
    op.rename_table("knowledge_products", "knowledge_profiles")
