"""Dataset Fabric profiles

Revision ID: 007
Revises: 006
Create Date: 2026-10-20

A dataset profile is the unit the Offline Evaluation page selects: a name, a purpose, and
the pipeline it grades. Its uploaded files live in MinIO, so the dataset row needs to
remember where the file was written.

``dataset_profiles``
    One row per profile. ``pipeline_slug`` NULL means "yet to be linked"; the datasets can
    be authored before the pipeline exists. ``knowledge_product_id`` and its name are
    snapshots from the ingestion service, because that service owns the Knowledge Product
    and its document bucket.

``golden_datasets``
    ``profile_id`` points at the profile and is NULL on a dataset imported the old way
    through the Offline Evaluation page.
    ``storage_bucket``, ``storage_key``, ``original_filename``, ``source_format`` and
    ``row_count`` record the uploaded file. All are NULL for a dataset created from a JSON
    body with no file behind it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "dataset_profiles" not in set(inspector.get_table_names()):
        op.create_table(
            "dataset_profiles",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("pipeline_slug", sa.String(), nullable=True),
            sa.Column("pipeline_name", sa.String(), nullable=True),
            sa.Column("knowledge_product_id", sa.String(), nullable=True),
            sa.Column("knowledge_product_name", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("name", name="uq_dataset_profiles_name"),
        )
        op.create_index(
            "ix_dataset_profiles_pipeline_slug", "dataset_profiles", ["pipeline_slug"]
        )

    existing = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "profile_id" not in existing:
        op.add_column(
            "golden_datasets",
            sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_golden_datasets_profile_id",
            "golden_datasets",
            "dataset_profiles",
            ["profile_id"],
            ["id"],
        )
        op.create_index("ix_golden_datasets_profile_id", "golden_datasets", ["profile_id"])

    for column in ("storage_bucket", "storage_key", "original_filename", "source_format"):
        if column not in existing:
            op.add_column("golden_datasets", sa.Column(column, sa.String(), nullable=True))
    if "row_count" not in existing:
        op.add_column("golden_datasets", sa.Column("row_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {column["name"] for column in inspector.get_columns("golden_datasets")}
    for column in ("row_count", "source_format", "original_filename", "storage_key", "storage_bucket"):
        if column in existing:
            op.drop_column("golden_datasets", column)
    if "profile_id" in existing:
        op.drop_index("ix_golden_datasets_profile_id", table_name="golden_datasets")
        op.drop_constraint("fk_golden_datasets_profile_id", "golden_datasets", type_="foreignkey")
        op.drop_column("golden_datasets", "profile_id")

    if "dataset_profiles" in set(inspector.get_table_names()):
        op.drop_index("ix_dataset_profiles_pipeline_slug", table_name="dataset_profiles")
        op.drop_table("dataset_profiles")
