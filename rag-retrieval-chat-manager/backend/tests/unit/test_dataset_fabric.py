from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_api.main import create_app


@pytest.fixture
def client():
    # The lifespan builds a pipeline, a retriever, and a Redis queue. These routes need
    # only the settings object, so it is set directly and the lifespan stays unrun.
    from rag_shared.config import get_settings

    app = create_app()
    app.state.settings = get_settings()
    return TestClient(app)


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def flush(self):
        pass

    def delete(self, obj):
        pass


def _post(client, content: bytes, filename: str, kind: str, profile_id=None):
    return client.post(
        f"/api/dataset-profiles/{profile_id or uuid4()}/datasets",
        files={"file": (filename, content, "application/octet-stream")},
        data={"kind": kind},
    )


CSV = b"question,ground_truth_answer,source_doc_id\nWhat is X?,X is Y.,Resume.pdf\n"
MULTI_TURN_CSV = (
    'question,turns\n'
    '"And for a manager?","[{""role"":""user"",""content"":""And for a manager?""}]"\n'
).encode()


def test_rejects_a_format_outside_the_allow_list(client):
    response = _post(client, b"x", "dataset.txt", "single_turn")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_rejects_an_unknown_kind(client):
    response = _post(client, CSV, "d.csv", "both")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_KIND"


def test_rejects_a_file_whose_rows_do_not_match_the_section(client):
    response = _post(client, MULTI_TURN_CSV, "d.csv", "single_turn")
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "KIND_MISMATCH"
    assert "multi-turn" in body["message"]


def test_rejects_an_empty_file(client):
    response = _post(client, b"   ", "d.csv", "single_turn")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMPTY_FILE"


def test_upload_writes_the_file_and_imports_the_rows(client):
    profile_id = uuid4()
    dataset_id = uuid4()
    profile = MagicMock(id=profile_id, name="Resume profile", knowledge_product_id=None)
    dataset = MagicMock(id=dataset_id, created_at=None)

    profile_repo = MagicMock()
    profile_repo.get.return_value = profile
    eval_repo = MagicMock()
    eval_repo.create_dataset.return_value = dataset

    put = AsyncMock(return_value="s3://dataset-fabric/datasets/x/single_turn/d.csv")

    with (
        patch("rag_api.routes.dataset_profiles._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.dataset_profile_repository.DatasetProfileRepository",
            return_value=profile_repo,
        ),
        patch(
            "rag_db.repositories.evaluation_repository.EvaluationRepository",
            return_value=eval_repo,
        ),
        patch("rag_api.routes.dataset_profiles.resolve_bucket", AsyncMock(return_value="dataset-fabric")),
        patch("rag_api.routes.dataset_profiles.put_dataset", put),
    ):
        response = _post(client, CSV, "d.csv", "single_turn", profile_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "single_turn"
    assert body["row_count"] == 1
    assert body["bucket"] == "dataset-fabric"
    assert body["key"] == f"datasets/{profile_id}/single_turn/d.csv"

    put.assert_awaited_once()
    kwargs = put.await_args.kwargs
    assert kwargs["bucket"] == "dataset-fabric"
    assert kwargs["key"] == f"datasets/{profile_id}/single_turn/d.csv"
    assert kwargs["data"] == CSV

    create_kwargs = eval_repo.create_dataset.call_args.kwargs
    assert create_kwargs["profile_id"] == profile_id
    assert create_kwargs["row_count"] == 1
    assert create_kwargs["storage_key"] == f"datasets/{profile_id}/single_turn/d.csv"
    assert eval_repo.add_dataset_item.call_count == 1


def test_xlsx_upload_imports_its_rows(client):
    import pandas as pd

    profile_id = uuid4()
    dataset = MagicMock(id=uuid4(), created_at=None)
    profile_repo = MagicMock()
    profile_repo.get.return_value = MagicMock(id=profile_id, name="P", knowledge_product_id=None)
    eval_repo = MagicMock()
    eval_repo.create_dataset.return_value = dataset

    frame = pd.DataFrame(
        [{"question": "What is X?", "ground_truth_answer": "X is Y.", "source_doc_id": "Resume.pdf"}]
    )
    buffer = __import__("io").BytesIO()
    frame.to_excel(buffer, index=False)

    with (
        patch("rag_api.routes.dataset_profiles._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.dataset_profile_repository.DatasetProfileRepository",
            return_value=profile_repo,
        ),
        patch(
            "rag_db.repositories.evaluation_repository.EvaluationRepository",
            return_value=eval_repo,
        ),
        patch("rag_api.routes.dataset_profiles.resolve_bucket", AsyncMock(return_value="b")),
        patch("rag_api.routes.dataset_profiles.put_dataset", AsyncMock()),
    ):
        response = _post(client, buffer.getvalue(), "d.xlsx", "single_turn", profile_id)

    assert response.status_code == 201, response.text
    assert response.json()["format"] == "xlsx"
    assert eval_repo.create_dataset.call_args.kwargs["row_count"] == 1


def test_a_linked_profile_writes_into_the_knowledge_product_bucket():
    import asyncio
    import httpx

    from rag_api.dataset_storage import resolve_bucket
    from rag_shared.config import Settings

    settings = Settings()

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "sources": [
                    {"minio_bucket": "source-resumes-ab12"},
                    {"minio_bucket": "local-notes"},
                    {"minio_bucket": "source-policies-cd34"},
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    with patch("rag_api.dataset_storage.httpx.AsyncClient", return_value=_Client()):
        bucket = asyncio.run(resolve_bucket(settings, "kp-1"))

    assert bucket == "source-policies-cd34", "the local- bucket and the shared fallback are skipped"
