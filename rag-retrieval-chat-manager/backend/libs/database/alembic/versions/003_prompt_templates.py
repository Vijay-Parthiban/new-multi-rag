"""Prompt templates

Revision ID: 003
Revises: 002
Create Date: 2026-09-21

The old Prompts page wrote catalog overrides to a temp directory that nothing
read, and the assistant system message was hardcoded in
``generation_core/prompt_builder.py``. This adds a real table a pipeline can
attach, and seeds it with the prompt the code shipped with so a fresh install
has a working default.

The column definitions come from ``Base.metadata`` rather than being retyped, so
this migration cannot drift from ``rag_db/models/prompt.py``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "prompt_templates"


def _tables():
    from rag_db.models import prompt  # noqa: F401  (registers the table)
    from rag_db.models.base import Base

    return Base.metadata


def upgrade() -> None:
    from generation_core.prompt_builder import RAG_SYSTEM_PROMPT

    bind = op.get_bind()
    _tables().tables[_TABLE].create(bind, checkfirst=True)

    bind.execute(
        sa.text(
            "INSERT INTO prompt_templates (id, name, description, content) "
            "SELECT gen_random_uuid(), :name, :description, :content "
            "WHERE NOT EXISTS (SELECT 1 FROM prompt_templates)"
        ),
        {
            "name": "Default RAG",
            "description": "The prompt the code shipped with.",
            "content": RAG_SYSTEM_PROMPT,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    _tables().tables[_TABLE].drop(bind, checkfirst=True)
