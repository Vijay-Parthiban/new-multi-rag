"""Synthetic dataset profiles and versions

Revision ID: 009
Revises: 008
Create Date: 2026-11-03

``synthetic_dataset_profiles``
    One row per profile: a Knowledge Product, and the Qdrant collection its chunks live in.
    The collection name is fixed here, so a product re-ingested into a new collection needs
    a new profile rather than an update.

``synthetic_dataset_versions``
    One row per generation run. ``config`` holds the request whole so a run is repeatable,
    and ``progress`` holds the counters the page polls. ``fabric_profile_id`` links the
    produced rows to a Dataset Fabric profile so Offline Evaluation can select them.

``golden_datasets.synthetic_version_id``
    Points a produced dataset back at its version. NULL on every dataset uploaded by hand.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "synthetic_dataset_profiles" not in tables:
        op.create_table(
            "synthetic_dataset_profiles",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("knowledge_product_id", sa.String(), nullable=False),
            sa.Column("knowledge_product_name", sa.String(), nullable=True),
            sa.Column("qdrant_collection", sa.String(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("name", name="uq_synthetic_dataset_profiles_name"),
        )
        op.create_index(
            "ix_synthetic_dataset_profiles_knowledge_product_id",
            "synthetic_dataset_profiles",
            ["knowledge_product_id"],
        )

    if "synthetic_dataset_versions" not in tables:
        op.create_table(
            "synthetic_dataset_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("progress", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("fabric_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("row_count_single", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_count_multi", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["profile_id"],
                ["synthetic_dataset_profiles.id"],
                name="fk_synthetic_dataset_versions_profile_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["fabric_profile_id"],
                ["dataset_profiles.id"],
                name="fk_synthetic_dataset_versions_fabric_profile_id",
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint("profile_id", "version_no", name="uq_synthetic_version_no"),
        )
        op.create_index(
            "ix_synthetic_dataset_versions_profile_id",
            "synthetic_dataset_versions",
            ["profile_id"],
        )

    existing = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "synthetic_version_id" not in existing:
        op.add_column(
            "golden_datasets",
            sa.Column("synthetic_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_golden_datasets_synthetic_version_id",
            "golden_datasets",
            "synthetic_dataset_versions",
            ["synthetic_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_golden_datasets_synthetic_version_id", "golden_datasets", ["synthetic_version_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    existing = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "synthetic_version_id" in existing:
        op.drop_index("ix_golden_datasets_synthetic_version_id", table_name="golden_datasets")
        op.drop_constraint(
            "fk_golden_datasets_synthetic_version_id", "golden_datasets", type_="foreignkey"
        )
        op.drop_column("golden_datasets", "synthetic_version_id")

    if "synthetic_dataset_versions" in tables:
        op.drop_index(
            "ix_synthetic_dataset_versions_profile_id", table_name="synthetic_dataset_versions"
        )
        op.drop_table("synthetic_dataset_versions")

    if "synthetic_dataset_profiles" in tables:
        op.drop_index(
            "ix_synthetic_dataset_profiles_knowledge_product_id",
            table_name="synthetic_dataset_profiles",
        )
        op.drop_table("synthetic_dataset_profiles")
