"""Initial schema generated from SQLAlchemy metadata."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

file_status = postgresql.ENUM(
    "processing", "synced", "failed", "deleted", "duplicate", name="file_status", create_type=True
)
job_status = postgresql.ENUM(
    "pending", "processing", "success", "failed", name="job_status", create_type=True
)
job_operation = postgresql.ENUM(
    "upload", "append", "rename", "delete", name="job_operation", create_type=True
)


def upgrade() -> None:
    op.create_table(
        "directories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_directories_name"), "directories", ["name"], unique=True)

    op.create_table(
        "files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("directory_id", sa.UUID(), nullable=False),
        sa.Column("original_name", sa.String(length=512), nullable=False),
        sa.Column("stored_name", sa.String(length=512), nullable=True),
        sa.Column("relative_path", sa.String(length=1024), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("client_content_hash", sa.String(length=64), nullable=True),
        sa.Column("hash_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("duplicate_of_file_id", sa.UUID(), nullable=True),
        sa.Column("status", file_status, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["directory_id"], ["directories.id"]),
        sa.ForeignKeyConstraint(["duplicate_of_file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_directory_id"), "files", ["directory_id"], unique=False)
    op.create_index(op.f("ix_files_content_hash"), "files", ["content_hash"], unique=False)
    op.create_index("ix_files_directory_content_hash", "files", ["directory_id", "content_hash"], unique=False)

    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("directory_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=True),
        sa.Column("operation", job_operation, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["directory_id"], ["directories.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sync_jobs_directory_id"), "sync_jobs", ["directory_id"], unique=False)

    op.create_table(
        "chunk_uploads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("directory_name", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("total_size", sa.Integer(), nullable=False),
        sa.Column("received_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("client_content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_file_id", sa.UUID(), nullable=True),
        sa.Column("operation", job_operation, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["target_file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("chunk_uploads")
    op.drop_table("sync_jobs")
    op.drop_table("files")
    op.drop_table("directories")
    job_operation.drop(op.get_bind(), checkfirst=True)
    job_status.drop(op.get_bind(), checkfirst=True)
    file_status.drop(op.get_bind(), checkfirst=True)
