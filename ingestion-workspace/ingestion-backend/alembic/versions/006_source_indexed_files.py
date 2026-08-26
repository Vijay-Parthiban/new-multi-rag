"""Allow indexed_files to track source-backed files (no files.id row exists).

Source files are virtual FileRecords backed by MinIO objects in the source
bucket. They do not exist in the files table, so file_id must be nullable
and source_id + file_key identify the object instead.

Revision ID: 006_source_indexed_files
Revises: 005_sources
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_source_indexed_files"
down_revision: Union[str, None] = "005_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # file_id becomes nullable; add source_id + file_key for source objects
    op.alter_column("indexed_files", "file_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "indexed_files",
        sa.Column("source_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "indexed_files",
        sa.Column("file_key", sa.String(length=1024), nullable=True),
    )
    op.create_foreign_key(
        "fk_indexed_files_source_id_sources",
        "indexed_files",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_indexed_files_pipeline_source_key",
        "indexed_files",
        ["pipeline_id", "source_id", "file_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_indexed_files_pipeline_source_key", table_name="indexed_files")
    op.drop_constraint("fk_indexed_files_source_id_sources", "indexed_files", type_="foreignkey")
    op.drop_column("indexed_files", "file_key")
    op.drop_column("indexed_files", "source_id")
    op.alter_column("indexed_files", "file_id", existing_type=sa.UUID(), nullable=False)
