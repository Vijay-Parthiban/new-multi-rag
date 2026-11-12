"""A dataset profile links to the pipeline whose traces it validates.

Revision ID: 013
Revises: 012
Create Date: 2026-11-06

The link lives on the profile the Dataset Validator selects, not on the Dataset Fabric
profile. Two workspace profiles of one Knowledge Product can share one Fabric profile, so
the Fabric link cannot tell them apart. The backfill copies the Fabric profile's link, so
the profiles that the old Dataset Feedback page could open stay openable.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "synthetic_dataset_profiles" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "pipeline_slug" not in columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("pipeline_slug", sa.String(), nullable=True),
        )
    if "pipeline_name" not in columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("pipeline_name", sa.String(), nullable=True),
        )

    op.execute(
        """
        update synthetic_dataset_profiles p
        set pipeline_slug = d.pipeline_slug,
            pipeline_name = d.pipeline_name
        from dataset_profiles d
        where p.fabric_profile_id = d.id
          and p.pipeline_slug is null
          and d.pipeline_slug is not null
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "synthetic_dataset_profiles" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "pipeline_name" in columns:
        op.drop_column("synthetic_dataset_profiles", "pipeline_name")
    if "pipeline_slug" in columns:
        op.drop_column("synthetic_dataset_profiles", "pipeline_slug")
