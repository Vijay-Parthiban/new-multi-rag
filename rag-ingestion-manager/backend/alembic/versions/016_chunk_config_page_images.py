"""Add chunk_config and image_embedding_model, drop the caption columns

Revision ID: 016_chunk_config_page_images
Revises: 015_source_webscrape
Create Date: 2026-10-08

The profile form now offers eight chunk strategies, and a strategy carries its own
settings. Those settings live in one JSON column, ``chunk_config``, instead of a
column per parameter.

The ``text_images`` modality changed meaning. It used to caption each embedded
figure with a vision model; it now renders every document page to an image and
embeds that image with a multimodal embedding model, named per profile by
``image_embedding_model``. ``caption_model`` and ``image_min_pixels`` have no
reader after that change, so they go.

PostgreSQL only: ``Base.metadata.create_all`` never alters an existing table, and
SQLite is patched by ``_ensure_sqlite_columns`` in ``src/shared/db/session.py``,
which only adds columns and so leaves the two dropped ones unused.

``chunk_strategy`` is a native PostgreSQL enum type, not a text column, so the
three new strategy names must be added to the type itself. A value added here
cannot be used in the same transaction, and this migration only adds it, so the
statement is safe. PostgreSQL has no ``DROP VALUE``, so the downgrade leaves the
three labels in place: an unused label is harmless, and the Python enum no longer
names it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "016_chunk_config_page_images"
down_revision: Union[str, None] = "015_source_webscrape"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column, type). The types match the SQLAlchemy model.
_ADDED = (
    ("chunk_config", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("image_embedding_model", "VARCHAR(128) DEFAULT 'nvidia-embed-multimodal'"),
)
_DROPPED = (
    ("caption_model", "VARCHAR(128)"),
    ("image_min_pixels", "INTEGER DEFAULT 10000"),
)
# The strategies the profile form offers that the type did not have. ``sentence``
# and ``layout`` stay: a profile that already stores one must keep reading.
_NEW_STRATEGY_LABELS = ("contextual", "page_level", "sentence_window")

_CHUNK_STRATEGY_TYPE = "chunk_strategy"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for column, column_type in _ADDED:
        op.execute(
            f"ALTER TABLE ingestion_profiles ADD COLUMN IF NOT EXISTS {column} {column_type}"
        )
    for column, _ in _DROPPED:
        op.execute(f"ALTER TABLE ingestion_profiles DROP COLUMN IF EXISTS {column}")
    for label in _NEW_STRATEGY_LABELS:
        op.execute(f"ALTER TYPE {_CHUNK_STRATEGY_TYPE} ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    if not _is_postgres():
        return
    for column, column_type in _DROPPED:
        op.execute(
            f"ALTER TABLE ingestion_profiles ADD COLUMN IF NOT EXISTS {column} {column_type}"
        )
    for column, _ in _ADDED:
        op.execute(f"ALTER TABLE ingestion_profiles DROP COLUMN IF EXISTS {column}")
