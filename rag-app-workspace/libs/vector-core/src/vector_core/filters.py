from __future__ import annotations

from qdrant_client.http import models as qmodels

from rag_shared.types import SourceTypeFilter

SOURCE_TYPE_FIELD = "source_type"
SOURCE_ID_FIELD = "source_id"
LEGACY_SCRAPE_JOB_ID_FIELD = "scrape_job_id"


def build_source_filter(
    *,
    source_type: SourceTypeFilter = "all",
    source_id: str | None = None,
) -> qmodels.Filter | None:
    """Build a Qdrant payload filter for source_type and/or source_id."""
    must: list[qmodels.Condition] = []

    if source_type != "all":
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

    if not must:
        return None
    return qmodels.Filter(must=must)
