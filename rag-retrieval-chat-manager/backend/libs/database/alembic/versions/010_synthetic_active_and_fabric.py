"""Active profiles and versions, and the fabric profile a synthetic profile owns.

Revision ID: 010
Revises: 009
Create Date: 2026-11-05

A Knowledge Product has many synthetic profiles but only one active one. A synthetic
profile has many versions but only one active one. Partial unique indexes make both a
database rule.

A synthetic profile is created with a name and a description only, so it resolves the
Dataset Fabric profile of its Knowledge Product once and its versions inherit it. Without
a fabric profile, Offline Evaluation cannot select the generated rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "synthetic_dataset_profiles" not in tables:
        return

    profile_columns = {
        column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")
    }
    if "is_active" not in profile_columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "fabric_profile_id" not in profile_columns:
        op.add_column(
            "synthetic_dataset_profiles",
            sa.Column("fabric_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_synthetic_profiles_fabric_profile",
            "synthetic_dataset_profiles",
            "dataset_profiles",
            ["fabric_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )

    version_columns = {
        column["name"] for column in inspector.get_columns("synthetic_dataset_versions")
    }
    if "is_active" not in version_columns:
        op.add_column(
            "synthetic_dataset_versions",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    op.execute(
        "create unique index if not exists uq_synthetic_profile_active "
        "on synthetic_dataset_profiles (knowledge_product_id) where is_active"
    )
    op.execute(
        "create unique index if not exists uq_synthetic_version_active "
        "on synthetic_dataset_versions (profile_id) where is_active"
    )

    op.execute(
        """
        update synthetic_dataset_profiles p
        set fabric_profile_id = (
            select d.id from dataset_profiles d
            where d.knowledge_product_id = p.knowledge_product_id
            order by d.created_at asc
            limit 1
        )
        where p.fabric_profile_id is null
        """
    )
    op.execute(
        """
        update synthetic_dataset_versions v
        set fabric_profile_id = p.fabric_profile_id
        from synthetic_dataset_profiles p
        where v.profile_id = p.id
          and v.fabric_profile_id is null
          and p.fabric_profile_id is not null
        """
    )

    # Start the toggles from a sensible state: the oldest profile of a product and the
    # newest version of a profile.
    op.execute(
        """
        update synthetic_dataset_profiles p
        set is_active = true
        where p.id in (
            select distinct on (knowledge_product_id) id
            from synthetic_dataset_profiles
            order by knowledge_product_id, created_at asc
        )
        and not exists (
            select 1 from synthetic_dataset_profiles q
            where q.knowledge_product_id = p.knowledge_product_id and q.is_active
        )
        """
    )
    op.execute(
        """
        update synthetic_dataset_versions v
        set is_active = true
        where v.id in (
            select distinct on (profile_id) id
            from synthetic_dataset_versions
            order by profile_id, version_no desc
        )
        and not exists (
            select 1 from synthetic_dataset_versions w
            where w.profile_id = v.profile_id and w.is_active
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "synthetic_dataset_profiles" not in tables:
        return

    op.execute("drop index if exists uq_synthetic_version_active")
    op.execute("drop index if exists uq_synthetic_profile_active")

    version_columns = {
        column["name"] for column in inspector.get_columns("synthetic_dataset_versions")
    }
    if "is_active" in version_columns:
        op.drop_column("synthetic_dataset_versions", "is_active")

    profile_columns = {
        column["name"] for column in inspector.get_columns("synthetic_dataset_profiles")
    }
    if "fabric_profile_id" in profile_columns:
        op.drop_constraint(
            "fk_synthetic_profiles_fabric_profile",
            "synthetic_dataset_profiles",
            type_="foreignkey",
        )
        op.drop_column("synthetic_dataset_profiles", "fabric_profile_id")
    if "is_active" in profile_columns:
        op.drop_column("synthetic_dataset_profiles", "is_active")
