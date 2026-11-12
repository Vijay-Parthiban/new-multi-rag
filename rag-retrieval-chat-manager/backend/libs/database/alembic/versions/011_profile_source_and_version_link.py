"""Two authors of a dataset profile, and one version link for both.

Revision ID: 011
Revises: 010
Create Date: 2026-11-06

The Synthetic Dataset Creator and the Uploaded Datasets page both group datasets as a
profile with numbered versions. They share the tables, so `source` separates the two
authors and the page filters on it. The active profile of a Knowledge Product is per
source: a manual profile and a synthetic profile can both be active for the same product.

A version also holds uploaded datasets, so the link from `golden_datasets` to its version
is no longer synthetic-only and loses that prefix.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "synthetic_dataset_profiles" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "source" not in columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("source", sa.String(), nullable=False, server_default="synthetic"),
        )
        op.execute("update synthetic_dataset_profiles set source = 'synthetic'")
        op.alter_column("synthetic_dataset_profiles", "source", server_default=None)

    # A name may repeat between the two authors now, but not inside one of them.
    for constraint in inspector.get_unique_constraints("synthetic_dataset_profiles"):
        if set(constraint.get("column_names") or []) == {"name"}:
            op.drop_constraint(constraint["name"], "synthetic_dataset_profiles", type_="unique")
    op.execute(
        "create unique index if not exists uq_synthetic_profile_name_source "
        "on synthetic_dataset_profiles (name, source)"
    )

    op.execute("drop index if exists uq_synthetic_profile_active")
    op.execute(
        "create unique index if not exists uq_synthetic_profile_active "
        "on synthetic_dataset_profiles (knowledge_product_id, source) where is_active"
    )

    golden_columns = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "synthetic_version_id" in golden_columns and "version_id" not in golden_columns:
        op.alter_column("golden_datasets", "synthetic_version_id", new_column_name="version_id")
    op.execute(
        "alter index if exists ix_golden_datasets_synthetic_version_id "
        "rename to ix_golden_datasets_version_id"
    )
    renamed = bind.execute(
        sa.text(
            "select 1 from pg_constraint where conname = 'fk_golden_datasets_synthetic_version_id'"
        )
    ).scalar()
    if renamed:
        op.execute(
            "alter table golden_datasets rename constraint "
            "fk_golden_datasets_synthetic_version_id to fk_golden_datasets_version_id"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "synthetic_dataset_profiles" not in tables:
        return

    golden_columns = {column["name"] for column in inspector.get_columns("golden_datasets")}
    if "version_id" in golden_columns and "synthetic_version_id" not in golden_columns:
        op.alter_column("golden_datasets", "version_id", new_column_name="synthetic_version_id")
    op.execute(
        "alter index if exists ix_golden_datasets_version_id "
        "rename to ix_golden_datasets_synthetic_version_id"
    )
    renamed = bind.execute(
        sa.text("select 1 from pg_constraint where conname = 'fk_golden_datasets_version_id'")
    ).scalar()
    if renamed:
        op.execute(
            "alter table golden_datasets rename constraint "
            "fk_golden_datasets_version_id to fk_golden_datasets_synthetic_version_id"
        )

    op.execute("delete from synthetic_dataset_profiles where source = 'manual'")
    op.execute("drop index if exists uq_synthetic_profile_active")
    op.execute(
        "create unique index if not exists uq_synthetic_profile_active "
        "on synthetic_dataset_profiles (knowledge_product_id) where is_active"
    )
    op.execute("drop index if exists uq_synthetic_profile_name_source")
    op.create_unique_constraint(
        "synthetic_dataset_profiles_name_key", "synthetic_dataset_profiles", ["name"]
    )

    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "source" in columns:
        op.drop_column("synthetic_dataset_profiles", "source")
