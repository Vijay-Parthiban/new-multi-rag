"""Every version dataset belongs to the profile's Dataset Fabric profile.

Revision ID: 014
Revises: 013
Create Date: 2026-11-06

A synthetic dataset was created while its version had no Fixture profile id yet, so the
row kept a null or old `profile_id`. The Dataset Validator reads a dataset through its
Fabric profile, so those rows were invisible. This sets the profile on every version and
then on every dataset a version holds.

The rule afterwards is one profile per Knowledge Product: the profile owns its versions,
and each version owns one dataset per kind.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if not {"synthetic_dataset_profiles", "synthetic_dataset_versions"}.issubset(tables):
        return

    op.execute(
        """
        update synthetic_dataset_versions v
        set fabric_profile_id = p.fabric_profile_id
        from synthetic_dataset_profiles p
        where v.profile_id = p.id
          and v.fabric_profile_id is distinct from p.fabric_profile_id
          and p.fabric_profile_id is not null
        """
    )
    op.execute(
        """
        update golden_datasets d
        set profile_id = v.fabric_profile_id
        from synthetic_dataset_versions v
        where d.version_id = v.id
          and d.profile_id is distinct from v.fabric_profile_id
          and v.fabric_profile_id is not null
        """
    )


def downgrade() -> None:
    # The repair has no inverse: the previous values were wrong.
    pass
