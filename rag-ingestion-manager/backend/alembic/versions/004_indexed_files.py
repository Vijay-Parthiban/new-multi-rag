"""Add indexed_files table for tracking per-pipeline file indexing state."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_indexed_files"
down_revision: Union[str, None] = "003_pipeline_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "indexed_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pipeline_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_indexed_files_pipeline_content_hash",
        "indexed_files",
        ["pipeline_id", "content_hash"],
        unique=True,
    )
    op.create_index(
        "ix_indexed_files_pipeline_file",
        "indexed_files",
        ["pipeline_id", "file_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_indexed_files_pipeline_file", table_name="indexed_files")
    op.drop_index("ix_indexed_files_pipeline_content_hash", table_name="indexed_files")
    op.drop_table("indexed_files")
