"""Add pipeline configuration and run tracking tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_pipelines"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

rag_strategy = postgresql.ENUM(
    "naive", "sparse", "hybrid", "multimodal", "metadata", name="rag_strategy", create_type=False
)
index_modality = postgresql.ENUM("text", "image", name="index_modality", create_type=False)


def upgrade() -> None:
    rag_strategy.create(op.get_bind(), checkfirst=True)
    index_modality.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pipelines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rag_strategy", rag_strategy, nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("modality", index_modality, nullable=True),
        sa.Column("directory_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("qdrant_collection", sa.String(length=128), nullable=True),
        sa.Column("web_scraper_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("scraper_seed_url", sa.String(length=2048), nullable=True),
        sa.Column("scraper_max_depth", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("scraper_max_pages", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("scraper_mode", sa.String(length=32), nullable=False, server_default="httpx"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipelines_name"), "pipelines", ["name"], unique=True)

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pipeline_id", sa.UUID(), nullable=False),
        sa.Column("status", postgresql.ENUM(name="job_status", create_type=False), nullable=False),
        sa.Column("files_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_indexed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scraper_crawl_job_id", sa.String(length=64), nullable=True),
        sa.Column("scraper_scrape_job_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipeline_runs_pipeline_id"), "pipeline_runs", ["pipeline_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pipeline_runs_pipeline_id"), table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index(op.f("ix_pipelines_name"), table_name="pipelines")
    op.drop_table("pipelines")
    index_modality.drop(op.get_bind(), checkfirst=True)
    rag_strategy.drop(op.get_bind(), checkfirst=True)
