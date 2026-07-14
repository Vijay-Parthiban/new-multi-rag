from qdrant_client.http import models as qmodels

SOURCE_TYPE_FIELD = "source_type"
SOURCE_ID_FIELD = "source_id"
LEGACY_SCRAPE_JOB_ID_FIELD = "scrape_job_id"


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
    """Build a Qdrant payload filter supporting source_type, source_id, pipeline_id, and other fields."""
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

    if pipeline_id:
        must.append(
            qmodels.FieldCondition(
                key="pipeline_id",
                match=qmodels.MatchValue(value=pipeline_id),
            )
        )

    if file_id:
        must.append(
            qmodels.FieldCondition(
                key="file_id",
                match=qmodels.MatchValue(value=file_id),
            )
        )

    if directory_name:
        must.append(
            qmodels.FieldCondition(
                key="directory_name",
                match=qmodels.MatchValue(value=directory_name),
            )
        )

    if original_name:
        must.append(
            qmodels.FieldCondition(
                key="original_name",
                match=qmodels.MatchValue(value=original_name),
            )
        )

    if mime_type:
        must.append(
            qmodels.FieldCondition(
                key="mime_type",
                match=qmodels.MatchValue(value=mime_type),
            )
        )

    if rag_strategy:
        must.append(
            qmodels.FieldCondition(
                key="rag_strategy",
                match=qmodels.MatchValue(value=rag_strategy),
            )
        )

    if not must:
        return None
    return qmodels.Filter(must=must)
