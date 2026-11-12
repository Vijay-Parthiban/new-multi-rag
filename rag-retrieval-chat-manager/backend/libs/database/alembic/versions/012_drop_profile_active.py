"""Only a version is active, not a profile.

Revision ID: 012
Revises: 011
Create Date: 2026-11-06

A profile is a folder: it holds versions, and it is never the thing an evaluation picks.
The active flag on a profile therefore carried no meaning, so the column and its partial
unique index go. The version keeps its own flag and its own index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "synthetic_dataset_profiles" not in set(inspector.get_table_names()):
        return

    op.execute("drop index if exists uq_synthetic_profile_active")
    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "is_active" in columns:
        op.drop_column("synthetic_dataset_profiles", "is_active")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "synthetic_dataset_profiles" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")}
    if "is_active" not in columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    op.execute(
        """
        update synthetic_dataset_profiles p
        set is_active = true
        where p.id in (
            select distinct on (knowledge_product_id, source) id
            from synthetic_dataset_profiles
            order by knowledge_product_id, source, created_at asc
        )
        """
    )
    op.execute(
        "create unique index if not exists uq_synthetic_profile_active "
        "on synthetic_dataset_profiles (knowledge_product_id, source) where is_active"
    )
