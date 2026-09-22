"""Trace mode and OTEL ids on a chat turn

Revision ID: 004
Revises: 003
Create Date: 2026-09-22

Adds three columns to ``chat_pipeline_traces``:

``trace_mode``
    "test" for a turn sent from the Chat page, "prod" for a turn sent to the callable
    endpoint. It comes from the ``X-RAG-Trace-Mode`` request header, and a request without
    the header is production. The Real Time Monitoring page tags every log with it.

``otel_trace_id`` / ``otel_span_id``
    The OpenTelemetry ids of the turn's span, as hex. They are the join point that lets the
    metrics worker, which runs later in a different process, file its span into the same
    trace. Without them the worker opens a second trace and one question shows up twice in
    Langfuse and Phoenix.

Every column is nullable or server-defaulted, so existing rows need no backfill: a row
written before this migration reads back as ``prod`` with no OTEL ids.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "chat_pipeline_traces"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}

    if "trace_mode" not in existing:
        op.add_column(
            _TABLE,
            sa.Column("trace_mode", sa.String(), nullable=False, server_default="prod"),
        )
    if "otel_trace_id" not in existing:
        op.add_column(_TABLE, sa.Column("otel_trace_id", sa.String(length=32), nullable=True))
    if "otel_span_id" not in existing:
        op.add_column(_TABLE, sa.Column("otel_span_id", sa.String(length=16), nullable=True))


def downgrade() -> None:
    for name in ("otel_span_id", "otel_trace_id", "trace_mode"):
        op.drop_column(_TABLE, name)
