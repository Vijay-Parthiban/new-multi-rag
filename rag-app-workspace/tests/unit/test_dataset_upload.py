from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from eval_core.dataset_schema import parse_golden_dataset_json
from fastapi.testclient import TestClient

from rag_api.main import create_app

DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "golden" / "golden-dataset.json"


@pytest.fixture
def client():
    return TestClient(create_app())


def test_parse_golden_dataset_json():
    payload = parse_golden_dataset_json(DATASET_PATH.read_text(encoding="utf-8"))
    assert payload.name == "scrape-corpus-golden"
    assert len(payload.items) >= 20


@patch("rag_db.repositories.evaluation_repository.EvaluationRepository")
@patch("rag_db.services.database.get_session_factory")
def test_upload_dataset_json_file(mock_session_factory, mock_repo_cls, client):
    dataset_id = uuid4()
    mock_dataset = MagicMock()
    mock_dataset.id = dataset_id
    mock_dataset.name = "scrape-corpus-golden"

    mock_repo = MagicMock()
    mock_repo.import_dataset.return_value = mock_dataset
    mock_repo.count_dataset_items.return_value = 32
    mock_repo_cls.return_value = mock_repo
    mock_session_factory.return_value = MagicMock()

    with DATASET_PATH.open("rb") as handle:
        response = client.post(
            "/evaluate/datasets/upload",
            files={"file": ("golden-dataset.json", handle, "application/json")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == str(dataset_id)
    assert body["name"] == "scrape-corpus-golden"
    assert body["item_count"] == 32
    assert body["replaced"] is False


@patch("rag_db.repositories.evaluation_repository.EvaluationRepository")
@patch("rag_db.services.database.get_session_factory")
def test_create_dataset_json_body(mock_session_factory, mock_repo_cls, client):
    dataset_id = uuid4()
    mock_dataset = MagicMock()
    mock_dataset.id = dataset_id
    mock_dataset.name = "scrape-corpus-golden"

    mock_repo = MagicMock()
    mock_repo.import_dataset.return_value = mock_dataset
    mock_repo.count_dataset_items.return_value = 32
    mock_repo_cls.return_value = mock_repo
    mock_session_factory.return_value = MagicMock()

    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    response = client.post("/evaluate/datasets", json=payload)

    assert response.status_code == 200
    assert response.json()["dataset_id"] == str(dataset_id)


def test_upload_dataset_rejects_non_json(client):
    response = client.post(
        "/evaluate/datasets/upload",
        files={"file": ("dataset.txt", b"not json", "text/plain")},
    )
    assert response.status_code == 422


@patch("rag_db.repositories.evaluation_repository.EvaluationRepository")
@patch("rag_db.services.database.get_session_factory")
def test_create_dataset_conflict(mock_session_factory, mock_repo_cls, client):
    mock_repo = MagicMock()
    mock_repo.import_dataset.side_effect = ValueError("Dataset 'x' already exists")
    mock_repo_cls.return_value = mock_repo
    mock_session_factory.return_value = MagicMock()

    payload = {
        "name": "x",
        "items": [
            {
                "question": "q?",
                "ground_truth_answer": "a",
                "expected_sources": [],
            }
        ],
    }
    response = client.post("/evaluate/datasets", json=payload)
    assert response.status_code == 409
