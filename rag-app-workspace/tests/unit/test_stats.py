from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_api.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_evaluation_stats_limit_validation(client):
    response = client.get("/evaluate/stats", params={"limit": 0})
    assert response.status_code == 422


def test_chat_stats_limit_validation(client):
    response = client.get("/chat/stats", params={"limit": 200})
    assert response.status_code == 422


@patch("rag_db.repositories.evaluation_repository.EvaluationRepository")
@patch("rag_db.services.database.get_session_factory")
def test_evaluation_stats_returns_runs(mock_session_factory, mock_repo_cls, client):
    run_id = uuid4()
    dataset_id = uuid4()
    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.dataset_id = dataset_id
    mock_run.status = "completed"
    mock_run.config = {"mode": "hybrid"}
    mock_run.aggregate_metrics = {"mean_mrr": 0.8, "item_count": 2}
    mock_run.created_at = None
    mock_run.started_at = None
    mock_run.completed_at = None

    mock_repo = MagicMock()
    mock_repo.list_recent_run_stats.return_value = [mock_run]
    mock_repo_cls.return_value = mock_repo
    mock_db = MagicMock()
    mock_session_factory.return_value.return_value.__enter__.return_value = mock_db

    response = client.get("/evaluate/stats", params={"limit": 10})

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 10
    assert data["count"] == 1
    assert data["items"][0]["run_id"] == str(run_id)
    assert data["items"][0]["aggregate_metrics"]["mean_mrr"] == 0.8


@patch("rag_api.routes.chat.ChatRepository")
@patch("rag_api.routes.chat.get_session_factory")
def test_chat_stats_returns_metrics(mock_session_factory, mock_repo_cls, client):
    message_id = uuid4()
    session_id = uuid4()

    mock_metrics = MagicMock()
    mock_metrics.faithfulness = 0.9
    mock_metrics.answer_relevancy = 0.85
    mock_metrics.context_precision = 0.7
    mock_metrics.context_recall = None
    mock_metrics.status = "completed"
    mock_metrics.computed_at = None

    mock_message = MagicMock()
    mock_message.id = message_id
    mock_message.session_id = session_id
    mock_message.content = "Attention is a mechanism..."
    mock_message.created_at = None

    mock_trace = MagicMock()
    mock_trace.query = "What is attention?"
    mock_trace.latency_ms = {"total": 1200}
    mock_trace.retrieval_mode = "hybrid"
    mock_trace.rerank_enabled = True

    mock_repo = MagicMock()
    mock_repo.list_recent_metrics_stats.return_value = [(mock_metrics, mock_message, mock_trace)]
    mock_repo_cls.return_value = mock_repo
    mock_db = MagicMock()
    mock_session_factory.return_value.return_value.__enter__.return_value = mock_db

    response = client.get("/chat/stats", params={"limit": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["query"] == "What is attention?"
    assert data["items"][0]["faithfulness"] == 0.9


@patch("rag_api.routes.chat.ChatRepository")
@patch("rag_api.routes.chat.get_session_factory")
def test_list_chat_sessions(mock_session_factory, mock_repo_cls, client):
    session_id = uuid4()
    mock_session = MagicMock()
    mock_session.id = session_id
    mock_session.created_at = None

    mock_repo = MagicMock()
    mock_repo.list_sessions.return_value = [(mock_session, 4, None, "What is attention?")]
    mock_repo_cls.return_value = mock_repo
    mock_db = MagicMock()
    mock_session_factory.return_value.return_value.__enter__.return_value = mock_db

    response = client.get("/chat/sessions", params={"limit": 10})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["session_id"] == str(session_id)
    assert data["items"][0]["preview"] == "What is attention?"
    assert data["items"][0]["message_count"] == 4


def test_list_chat_sessions_limit_validation(client):
    response = client.get("/chat/sessions", params={"limit": 0})
    assert response.status_code == 422


@patch("rag_api.routes.chat.ChatRepository")
@patch("rag_api.routes.chat.get_session_factory")
def test_get_chat_session_messages(mock_session_factory, mock_repo_cls, client):
    session_id = uuid4()
    user_message_id = uuid4()
    assistant_message_id = uuid4()

    mock_session = MagicMock()
    mock_user_message = MagicMock()
    mock_user_message.id = user_message_id
    mock_user_message.role = "user"
    mock_user_message.content = "What is attention?"
    mock_user_message.created_at = None

    mock_assistant_message = MagicMock()
    mock_assistant_message.id = assistant_message_id
    mock_assistant_message.role = "assistant"
    mock_assistant_message.content = "Attention is a mechanism..."
    mock_assistant_message.created_at = None

    mock_trace = MagicMock()
    mock_trace.retrieval_mode = "hybrid"
    mock_trace.rerank_enabled = True
    mock_trace.generation_model = "gpt-4"
    mock_trace.reranked_chunks = [
        {
            "source_locator": "doc-1",
            "chunk_index": 0,
            "rerank_score": 0.95,
        }
    ]

    mock_metrics = MagicMock()
    mock_metrics.status = "completed"

    mock_repo = MagicMock()
    mock_repo.get_session.return_value = mock_session
    mock_repo.list_session_messages.return_value = [
        (mock_user_message, None, None),
        (mock_assistant_message, mock_trace, mock_metrics),
    ]
    mock_repo_cls.return_value = mock_repo
    mock_db = MagicMock()
    mock_session_factory.return_value.return_value.__enter__.return_value = mock_db

    response = client.get(f"/chat/sessions/{session_id}/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(session_id)
    assert data["count"] == 2
    assert data["items"][0]["role"] == "user"
    assert data["items"][1]["role"] == "assistant"
    assert data["items"][1]["sources"][0]["source_locator"] == "doc-1"
    assert data["items"][1]["trace"]["generation_model"] == "gpt-4"
    assert data["items"][1]["metrics_status"] == "completed"


@patch("rag_api.routes.chat.ChatRepository")
@patch("rag_api.routes.chat.get_session_factory")
def test_get_chat_session_messages_not_found(mock_session_factory, mock_repo_cls, client):
    session_id = uuid4()

    mock_repo = MagicMock()
    mock_repo.get_session.return_value = None
    mock_repo_cls.return_value = mock_repo
    mock_db = MagicMock()
    mock_session_factory.return_value.return_value.__enter__.return_value = mock_db

    response = client.get(f"/chat/sessions/{session_id}/messages")

    assert response.status_code == 404
