import uuid

from qdrant_client.http import models as qmodels

from crawler_shared.types import WEB_SCRAPE_SOURCE_TYPE
from web_scrapper.vector.filters import build_source_filter
from web_scrapper.vector.hit_mapper import map_scored_point


def test_build_source_filter_all_returns_none() -> None:
    assert build_source_filter(source_type="all") is None
    assert build_source_filter(source_type="all", source_id=None) is None


def test_build_source_filter_source_type_only() -> None:
    query_filter = build_source_filter(source_type="web_scrape")
    assert query_filter is not None
    assert len(query_filter.must) == 1


def test_build_source_filter_source_id_matches_new_and_legacy_fields() -> None:
    query_filter = build_source_filter(source_type="all", source_id="job-123")
    assert query_filter is not None
    assert len(query_filter.must) == 1
    nested = query_filter.must[0]
    assert isinstance(nested, qmodels.Filter)
    assert len(nested.should) == 2


def test_map_scored_point_uses_canonical_source_fields() -> None:
    hit = qmodels.ScoredPoint(
        id=str(uuid.uuid4()),
        version=1,
        score=0.91,
        payload={
            "source_type": WEB_SCRAPE_SOURCE_TYPE,
            "source_id": "scrape-job-1",
            "source_locator": "https://example.com/page",
            "type": "text",
            "content": "hello world",
            "chunk_index": 2,
            "title": "Example",
            "scrape_job_id": "scrape-job-1",
            "url": "https://example.com/page",
        },
    )

    result = map_scored_point(hit)

    assert result["source_type"] == WEB_SCRAPE_SOURCE_TYPE
    assert result["source_id"] == "scrape-job-1"
    assert result["source_locator"] == "https://example.com/page"
    assert result["chunk_index"] == 2
    assert result["source_url"] == "https://example.com/page"
    assert result["scrape_job_id"] == "scrape-job-1"


def test_map_scored_point_falls_back_for_legacy_payload() -> None:
    hit = qmodels.ScoredPoint(
        id=str(uuid.uuid4()),
        version=1,
        score=0.5,
        payload={
            "type": "text",
            "content": "legacy chunk",
            "scrape_job_id": "legacy-job",
            "url": "https://legacy.example/page",
        },
    )

    result = map_scored_point(hit)

    assert result["source_type"] == WEB_SCRAPE_SOURCE_TYPE
    assert result["source_id"] == "legacy-job"
    assert result["source_locator"] == "https://legacy.example/page"
    assert result["chunk_index"] is None
