from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


MOCK_HIT = {
    "id": "abc-123",
    "score": 0.91,
    "type": "text",
    "content": "attention mechanism",
    "source_type": "web_scrape",
    "source_id": "job-1",
    "source_locator": "https://arxiv.org/html/1706.03762v7",
    "chunk_index": 0,
    "source_url": "https://arxiv.org/html/1706.03762v7",
    "title": "Attention",
    "scrape_job_id": "job-1",
}


@patch("rag_api.routes.search.search_scrape_chunks", return_value=[MOCK_HIT])
def test_get_search(mock_search, client):
    response = client.get(
        "/search",
        params={
            "query_text": "What is attention?",
            "limit": 5,
            "mode": "hybrid",
            "source_type": "web_scrape",
            "source_id": "job-1",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "abc-123"
    assert data[0]["scrape_job_id"] == "job-1"
    mock_search.assert_called_once()


@patch("rag_api.routes.search.search_scrape_chunks", return_value=[MOCK_HIT])
def test_post_scrapes_query(mock_search, client):
    response = client.post(
        "/scrapes/query",
        json={
            "text_query": "What is attention?",
            "limit": 5,
            "mode": "hybrid",
            "source_type": "web_scrape",
            "source_id": "job-1",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data[0]["content"] == "attention mechanism"
    mock_search.assert_called_once()
