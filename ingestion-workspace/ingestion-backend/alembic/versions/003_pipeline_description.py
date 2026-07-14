"""Add pipeline description and per-pipeline embedding/collection config."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_pipeline_description"
down_revision: Union[str, None] = "002_pipelines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipelines",
        sa.Column("description", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "pipelines",
        sa.Column("sparse_embedding_model", sa.String(length=128), nullable=True),
    )

    # Backfill description + collection for existing rows before NOT NULL / unique
    op.execute(
        sa.text(
            "UPDATE pipelines SET description = name WHERE description IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE pipelines SET qdrant_collection = 'pipeline_' || replace(id::text, '-', '') "
            "WHERE qdrant_collection IS NULL"
        )
    )

    op.alter_column("pipelines", "description", nullable=False)
    op.alter_column("pipelines", "qdrant_collection", nullable=False)
    op.create_index(op.f("ix_pipelines_description"), "pipelines", ["description"], unique=True)
    op.create_index(
        op.f("ix_pipelines_qdrant_collection"), "pipelines", ["qdrant_collection"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pipelines_qdrant_collection"), table_name="pipelines")
    op.drop_index(op.f("ix_pipelines_description"), table_name="pipelines")
    op.alter_column("pipelines", "qdrant_collection", nullable=True)
    op.drop_column("pipelines", "sparse_embedding_model")
    op.drop_column("pipelines", "description")
