"""Soft delete for conversations and single turns

Revision ID: 005
Revises: 004
Create Date: 2026-09-22

The Chat page can remove a whole conversation, and can remove one question
together with its reply. Both were wired up in the API and the UI, but the
columns they rely on were never added, so every delete answered 500.

``chat_sessions.deleted_at``
    Set when a conversation leaves the history list. The turns stay in the
    table, so the traces and metrics behind them survive for the evaluation
    and monitoring pages.

``chat_messages.deleted_at``
    Set per turn, so one question and its reply can go while the rest of the
    conversation stays.

Both are nullable with no default, so existing rows read back as live and need
no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {column["name"] for column in inspector.get_columns("chat_sessions")}
    if "deleted_at" not in existing:
        op.add_column(
            "chat_sessions",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing = {column["name"] for column in inspector.get_columns("chat_messages")}
    if "deleted_at" not in existing:
        op.add_column(
            "chat_messages",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("chat_messages", "deleted_at")
    op.drop_column("chat_sessions", "deleted_at")
