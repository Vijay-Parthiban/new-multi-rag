"""Conversation turns for Dataset Feedback

Revision ID: 008
Revises: 007
Create Date: 2026-10-29

``conversation_turns``
    One row per chat turn span the OpenTelemetry Collector posts to rag-api. No chat table
    stores the pipeline a turn belonged to; ``pipeline_slug`` here comes from the span
    attribute ``rag.pipeline.slug``. ``(trace_id, span_id)`` is unique so a collector retry
    never duplicates a turn.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "conversation_turns" in set(inspector.get_table_names()):
        return

    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("trace_id", sa.String(32), nullable=False),
        sa.Column("span_id", sa.String(16), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("pipeline_slug", sa.String(), nullable=True),
        sa.Column("trace_mode", sa.String(), nullable=False, server_default="prod"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("chunks_used", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("trace_id", "span_id", name="uq_conversation_turns_span"),
    )
    op.create_index(
        "ix_conversation_turns_slug_session",
        "conversation_turns",
        ["pipeline_slug", "session_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "conversation_turns" in set(inspector.get_table_names()):
        op.drop_index("ix_conversation_turns_slug_session", table_name="conversation_turns")
        op.drop_table("conversation_turns")
