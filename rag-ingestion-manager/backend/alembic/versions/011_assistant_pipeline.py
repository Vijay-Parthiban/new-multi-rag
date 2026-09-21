"""Assistant pipeline fields and the retrieval strategy labels

Revision ID: 011_assistant_pipeline
Revises: 010_knowledge_products
Create Date: 2026-09-21

A pipeline can now be a chat assistant: it reads one Knowledge Product's
stores instead of its own Qdrant collection, and it attaches a prompt template,
a guardrails config and a chat model. The chat endpoints address it by slug.

Both engines are supported. The service runs on SQLite when PostgreSQL is not
reachable, so the nullability change goes through ``batch_alter_table`` (a table
rebuild on SQLite, a plain ALTER on PostgreSQL) and the enum labels are added
only on PostgreSQL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "011_assistant_pipeline"
down_revision: Union[str, None] = "010_knowledge_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_STRATEGIES = ("vector", "lexical", "relational")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("slug", sa.String(64), nullable=True))
    op.add_column("pipelines", sa.Column("prompt_template_id", UUID(as_uuid=True), nullable=True))
    op.add_column("pipelines", sa.Column("guardrails_config_id", UUID(as_uuid=True), nullable=True))
    op.add_column("pipelines", sa.Column("chat_model", sa.String(128), nullable=True))

    # An assistant owns no collection: it reads the Knowledge Product's.
    with op.batch_alter_table("pipelines") as batch:
        batch.alter_column(
            "qdrant_collection", existing_type=sa.String(128), nullable=True
        )

    op.create_index("ix_pipelines_slug", "pipelines", ["slug"], unique=True)

    if _is_postgres():
        # SQLite stores an Enum as VARCHAR, so it has no type to extend.
        for value in _NEW_STRATEGIES:
            op.execute(sa.text(f"ALTER TYPE rag_strategy ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    op.drop_index("ix_pipelines_slug", table_name="pipelines")
    with op.batch_alter_table("pipelines") as batch:
        batch.alter_column(
            "qdrant_collection", existing_type=sa.String(128), nullable=False
        )
    op.drop_column("pipelines", "chat_model")
    op.drop_column("pipelines", "guardrails_config_id")
    op.drop_column("pipelines", "prompt_template_id")
    op.drop_column("pipelines", "slug")
    # PostgreSQL cannot drop a value from an enum type, so the three labels stay.
