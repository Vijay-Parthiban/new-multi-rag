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
        patch("rag_api.routes.dataset_profiles.resolve_bucket", MagicMock(return_value="dataset-fabric")),
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
        patch("rag_api.routes.dataset_profiles.resolve_bucket", MagicMock(return_value="b")),
        patch("rag_api.routes.dataset_profiles.put_dataset", AsyncMock()),
    ):
        response = _post(client, buffer.getvalue(), "d.xlsx", "single_turn", profile_id)

    assert response.status_code == 201, response.text
    assert response.json()["format"] == "xlsx"
    assert eval_repo.create_dataset.call_args.kwargs["row_count"] == 1


def test_every_dataset_goes_to_the_fabric_bucket():
    """A Knowledge Product bucket is an ingestion source, so a dataset must never land there."""
    from eval_core.dataset_storage import resolve_bucket
    from rag_shared.config import Settings

    settings = Settings(dataset_fabric_bucket="dataset-fabric")
    assert resolve_bucket(settings) == "dataset-fabric"


def _snapshot_fakes(filename="resume.csv", bucket="source-kp", key="datasets/x/single_turn/resume.csv"):
    from types import SimpleNamespace

    class _Db:
        committed = 0
        rolled = 0

        def commit(self):
            type(self).committed += 1

        def rollback(self):
            type(self).rolled += 1

    dataset = SimpleNamespace(
        id=uuid4(),
        created_at=None,
        original_filename=filename,
        storage_bucket=bucket,
        storage_key=key,
        source_format=None,
        row_count=None,
    )
    rows = [
        SimpleNamespace(
            question="q1",
            ground_truth_answer="a1",
            expected_sources=[{"name": "n.pdf"}],
            turns=None,
            metadata_={"question_type": "single_hop"},
            created_at=None,
        )
    ]
    repo = MagicMock()
    repo.list_dataset_items.return_value = rows
    repo.count_dataset_items.return_value = 1
    settings = SimpleNamespace(dataset_fabric_bucket="dataset-fabric")
    return settings, _Db(), repo, dataset


def test_store_snapshot_writes_jsonl_and_drops_the_old_object():
    import asyncio

    from eval_core.dataset_schema import parse_golden_dataset_jsonl
    from rag_api.routes.dataset_profiles import store_snapshot

    settings, db, repo, dataset = _snapshot_fakes()
    put, delete = AsyncMock(), AsyncMock()
    with (
        patch("rag_api.routes.dataset_profiles.put_dataset", put),
        patch("rag_api.routes.dataset_profiles.delete_stored_file", delete),
    ):
        asyncio.run(
            store_snapshot(settings, db, repo, dataset, profile_id=uuid4(), kind="single_turn")
        )

    kwargs = put.await_args.kwargs
    assert kwargs["bucket"] == "dataset-fabric"
    assert kwargs["key"].endswith("/single_turn/resume.jsonl")
    assert parse_golden_dataset_jsonl(kwargs["data"], name="t").items[0].question == "q1"
    assert dataset.storage_bucket == "dataset-fabric"
    assert dataset.row_count == 1
    delete.assert_awaited_once()
    assert delete.await_args.kwargs["bucket"] == "source-kp"


def test_store_snapshot_rolls_back_when_minio_refuses():
    import asyncio

    from fastapi import HTTPException
    from eval_core.dataset_storage import DatasetStorageError
    from rag_api.routes.dataset_profiles import store_snapshot

    settings, db, repo, dataset = _snapshot_fakes()
    with patch(
        "rag_api.routes.dataset_profiles.put_dataset",
        AsyncMock(side_effect=DatasetStorageError("down")),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                store_snapshot(settings, db, repo, dataset, profile_id=uuid4(), kind="single_turn")
            )
    assert exc.value.status_code == 503
    assert db.rolled == 1


# ── Preview and row editing ────────────────────────────────────────────────


def _row(question="q1", answer="a1", sources=None, turns=None, metadata=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        dataset_id=None,
        question=question,
        ground_truth_answer=answer,
        expected_sources=sources if sources is not None else [{"name": "a.pdf"}],
        turns=turns,
        metadata_=metadata or {},
    )


def _edit(client, *, kind="single_turn", item=None, body=None):
    """PATCH one row against fakes. Returns (response, row, store_snapshot mock)."""
    from types import SimpleNamespace

    profile_id = uuid4()
    dataset = SimpleNamespace(id=uuid4(), profile_id=profile_id, kind=kind)
    row = item or _row()
    row.dataset_id = dataset.id
    eval_repo = MagicMock()
    eval_repo.get_dataset.return_value = dataset
    eval_repo.get_dataset_item.return_value = row
    snapshot = AsyncMock()
    with (
        patch("rag_api.routes.dataset_profiles._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.evaluation_repository.EvaluationRepository",
            return_value=eval_repo,
        ),
        patch("rag_api.routes.dataset_profiles.store_snapshot", snapshot),
    ):
        response = client.patch(
            f"/api/dataset-profiles/{profile_id}/datasets/{dataset.id}/items/{row.id}",
            json=body if body is not None else {},
        )
    return response, row, snapshot


def test_preview_gives_every_row_its_id(client):
    from types import SimpleNamespace

    profile_id, dataset_id = uuid4(), uuid4()
    dataset = SimpleNamespace(
        id=dataset_id,
        profile_id=profile_id,
        original_filename="d.csv",
        kind="single_turn",
        row_count=1,
        storage_bucket="dataset-fabric",
        storage_key="k",
    )
    row = _row()
    row.dataset_id = dataset_id
    repo = MagicMock()
    repo.get_dataset.return_value = dataset
    repo.list_dataset_items.return_value = [row]

    with (
        patch("rag_api.routes.dataset_profiles._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.evaluation_repository.EvaluationRepository", return_value=repo
        ),
    ):
        response = client.get(f"/api/dataset-profiles/{profile_id}/datasets/{dataset_id}")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(row.id)


def test_edit_rewrites_the_row_and_the_snapshot(client):
    response, row, snapshot = _edit(
        client,
        body={"question": "new?", "ground_truth_answer": "new answer", "question_type": "multi_hop"},
    )
    assert response.status_code == 200, response.text
    assert row.question == "new?"
    assert row.ground_truth_answer == "new answer"
    assert row.metadata_["question_type"] == "multi_hop"
    snapshot.assert_awaited_once()
    assert snapshot.await_args.kwargs["kind"] == "single_turn"
    assert response.json()["question"] == "new?"


def test_edit_an_abstain_row_clears_the_answer_and_the_sources(client):
    response, row, _ = _edit(client, body={"expected_behavior": "refuse_or_abstain"})
    assert response.status_code == 200, response.text
    assert row.ground_truth_answer is None
    assert row.expected_sources == []
    assert row.metadata_["expected_behavior"] == "refuse_or_abstain"


def test_edit_normalizes_plain_source_names(client):
    response, row, _ = _edit(client, body={"expected_sources": [" a.pdf ", "b.pdf", "a.pdf"]})
    assert response.status_code == 200
    assert row.expected_sources == [{"name": "a.pdf"}, {"name": "b.pdf"}]


def test_turns_on_a_single_turn_row_are_refused(client):
    response, _, snapshot = _edit(
        client, body={"turns": [{"role": "user", "content": "q"}, {"role": "user", "content": "q2"}]}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "KIND_MISMATCH"
    snapshot.assert_not_awaited()


def test_a_blank_question_is_refused(client):
    response, _, snapshot = _edit(client, body={"question": "   "})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ROW"
    snapshot.assert_not_awaited()


def test_editing_a_row_of_another_dataset_is_404(client):
    response, _, _ = _edit(client, body={"question": "x"})
    # The helper points the row at its own dataset, so force a mismatch instead.
    assert response.status_code == 200

    from types import SimpleNamespace

    profile_id = uuid4()
    dataset = SimpleNamespace(id=uuid4(), profile_id=profile_id, kind="single_turn")
    row = _row()
    row.dataset_id = uuid4()  # another dataset's row
    repo = MagicMock()
    repo.get_dataset.return_value = dataset
    repo.get_dataset_item.return_value = row
    with (
        patch("rag_api.routes.dataset_profiles._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.evaluation_repository.EvaluationRepository", return_value=repo
        ),
    ):
        response = client.patch(
            f"/api/dataset-profiles/{profile_id}/datasets/{dataset.id}/items/{row.id}",
            json={"question": "x"},
        )
    assert response.status_code == 404
