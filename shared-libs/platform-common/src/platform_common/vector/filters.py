"""Qdrant payload filters shared across ingest and retrieval."""
from __future__ import annotations

from qdrant_client.http import models as qmodels

from platform_common.types import (
    LEGACY_SCRAPE_JOB_ID_FIELD,
    SOURCE_ID_FIELD,
    SOURCE_TYPE_FIELD,
)


def build_source_filter(
    *,
    source_type: str = "all",
    source_id: str | None = None,
    pipeline_id: str | None = None,
    file_id: str | None = None,
    directory_name: str | None = None,
    original_name: str | None = None,
    mime_type: str | None = None,
    rag_strategy: str | None = None,
) -> qmodels.Filter | None:
    """Build a Qdrant payload filter for source and optional file/pipeline fields."""
    must: list[qmodels.Condition] = []

    if source_type != "all" and source_type is not None:
        must.append(
            qmodels.FieldCondition(
                key=SOURCE_TYPE_FIELD,
                match=qmodels.MatchValue(value=source_type),
            )
        )

    if source_id:
        must.append(
            qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key=SOURCE_ID_FIELD,
                        match=qmodels.MatchValue(value=source_id),
                    ),
                    qmodels.FieldCondition(
                        key=LEGACY_SCRAPE_JOB_ID_FIELD,
                        match=qmodels.MatchValue(value=source_id),
                    ),
                ]
            )
        )

    for key, value in (
        ("pipeline_id", pipeline_id),
        ("file_id", file_id),
        ("directory_name", directory_name),
        ("original_name", original_name),
        ("mime_type", mime_type),
        ("rag_strategy", rag_strategy),
    ):
        if value:
            must.append(
                qmodels.FieldCondition(
                    key=key,
                    match=qmodels.MatchValue(value=value),
                )
            )

    if not must:
        return None
    return qmodels.Filter(must=must)
