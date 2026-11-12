from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from eval_core.dataset_schema import GoldenDatasetItemPayload
from fastapi.testclient import TestClient


from rag_api.main import create_app
from rag_api.routes.dataset_validator import FeedbackRow, RowRejected, build_item

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def _turn(n: int, question: str | None = None, mode: str = "prod"):
    return SimpleNamespace(
        question=question or f"q{n}",
        answer=f"a{n}",
        trace_id=f"t{n}",
        span_id=f"s{n}",
        trace_mode=mode,
        message_id=None,
    )


def _row(**kw) -> FeedbackRow:
    base = {"session_id": "sess", "ground_truth_answer": "Right.", "expected_sources": ["a.pdf"]}
    return FeedbackRow(**{**base, **kw})


# ── build_item ─────────────────────────────────────────────────────────────


def test_single_turn_item_carries_provenance_and_validates():
    item = build_item("single_turn", [_turn(1, mode="test")], _row(question_type="single_hop"), NOW)
    assert item["question"] == "q1"
    assert item["turns"] is None
    assert item["expected_sources"] == [{"name": "a.pdf"}]
    meta = item["metadata"]
    assert (meta["source"], meta["source_session_id"], meta["source_trace_id"]) == ("dataset_feedback", "sess", "t1")
    assert (meta["trace_mode"], meta["question_type"]) == ("test", "single_hop")
    assert GoldenDatasetItemPayload.model_validate(item).turns is None


def test_multi_turn_defaults_to_the_last_turn_and_keeps_user_turns_only():
    item = build_item("multi_turn", [_turn(1), _turn(2), _turn(3)], _row(), NOW)
    assert item["turns"] == [{"role": "user", "content": f"q{n}"} for n in (1, 2, 3)]
    assert item["question"] == "q3"
    assert item["metadata"]["source_span_id"] == "s3"
    # One answer per user turn, in order. The last is the row's ground truth.
    assert item["metadata"]["expected_turns"] == [
        {"content": "a1"},
        {"content": "a2"},
        {"content": "Right."},
    ]
    assert GoldenDatasetItemPayload.model_validate(item).metadata["expected_turns"] == [
        {"content": "a1"},
        {"content": "a2"},
        {"content": "Right."},
    ]


def test_multi_turn_graded_turn_cuts_the_conversation():
    item = build_item("multi_turn", [_turn(1), _turn(2), _turn(3)], _row(graded_turn=2), NOW)
    assert [t["content"] for t in item["turns"]] == ["q1", "q2"]
    assert item["question"] == "q2"
    assert item["metadata"]["expected_turns"] == [{"content": "a1"}, {"content": "Right."}]
    assert item["metadata"]["source_trace_id"] == "t2"
    assert GoldenDatasetItemPayload.model_validate(item).turns is not None


@pytest.mark.parametrize(
    "kind, turns, row",
    [
        ("multi_turn", [_turn(1)], _row()),
        ("single_turn", [_turn(1), _turn(2)], _row()),
        ("multi_turn", [_turn(1), _turn(2)], _row(graded_turn=3)),
    ],
)
def test_wrong_kind_is_rejected(kind, turns, row):
    with pytest.raises(RowRejected) as exc:
        build_item(kind, turns, row, NOW)
    assert exc.value.reason == "wrong_kind"


def test_blank_answer_is_rejected_unless_the_row_is_a_refusal():
    with pytest.raises(RowRejected) as exc:
        build_item("single_turn", [_turn(1)], _row(ground_truth_answer="  "), NOW)
    assert exc.value.reason == "answer_required"

    item = build_item("single_turn", [_turn(1)], _row(expected_behavior="refuse_or_abstain"), NOW)
    assert item["ground_truth_answer"] is None
    assert item["expected_sources"] == []
    assert item["metadata"]["expected_behavior"] == "refuse_or_abstain"

    refusal = build_item(
        "multi_turn", [_turn(1), _turn(2)], _row(expected_behavior="refuse_or_abstain"), NOW
    )
    assert "expected_turns" not in refusal["metadata"]


def test_question_type_is_stored_as_one_evolution():
    item = build_item("single_turn", [_turn(1)], _row(question_type="comparative"), NOW)
    assert item["metadata"]["evolutions"] == ["comparative"]


def test_sources_are_stripped_deduped_and_wrapped():
    item = build_item("single_turn", [_turn(1)], _row(expected_sources=[" a.pdf", "b.pdf", "a.pdf", " "]), NOW)
    assert item["expected_sources"] == [{"name": "a.pdf"}, {"name": "b.pdf"}]


# ── routes ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from rag_shared.config import get_settings

    app = create_app()
    app.state.settings = get_settings()
    return TestClient(app)


class _Db:
    rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def rollback(self):
        type(self).rolled_back = True


def _dataset(kind="single_turn", filename=None, key=None, profile_id=None):
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        created_at=NOW,
        original_filename=filename,
        source_format=None,
        row_count=None,
        storage_bucket="b" if key else None,
        storage_key=key,
        profile_id=profile_id,
    )


def _post(
    client,
    *,
    profile,
    version=None,
    target=None,
    seen=(),
    turns=None,
    kind="single_turn",
    rows=None,
):
    """Run POST /rows against fakes; returns (response, mocks)."""
    _Db.rolled_back = False
    version = version or _version()
    repo = MagicMock()
    repo.get_profile.return_value = profile
    repo.list_versions.return_value = [version]
    repo.datasets_for_version.return_value = [target] if target else []
    turns_repo = MagicMock()
    turns_repo.get_conversation.return_value = turns if turns is not None else [_turn(1)]
    created = _dataset(kind)
    eval_repo = MagicMock()
    eval_repo.create_dataset.return_value = created
    eval_repo.source_session_ids.return_value = set(seen)
    eval_repo.count_dataset_items.return_value = 1
    eval_repo.list_dataset_items.return_value = [
        SimpleNamespace(
            question="q1", ground_truth_answer="Right.", expected_sources=[{"name": "a.pdf"}],
            turns=None, metadata_={"source_session_id": "sess"}, created_at=NOW,
        )
    ]
    mocks = SimpleNamespace(
        snapshot=AsyncMock(), eval_repo=eval_repo, created=created, repo=repo, version=version
    )
    with ExitStack() as stack:
        for target_path, value in {
            "rag_api.routes.dataset_validator._session_factory": MagicMock(return_value=_Db),
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository": MagicMock(return_value=repo),
            "rag_db.repositories.conversation_turn_repository.ConversationTurnRepository": MagicMock(return_value=turns_repo),
            "rag_db.repositories.evaluation_repository.EvaluationRepository": MagicMock(return_value=eval_repo),
            "rag_api.routes.dataset_validator.store_snapshot": mocks.snapshot,
        }.items():
            stack.enter_context(patch(target_path, value))
        response = client.post(
            f"/api/dataset-validator/profiles/{profile.id}/rows",
            json={"kind": kind, "rows": rows or [{"session_id": "sess", "ground_truth_answer": "Right.", "expected_sources": ["a.pdf"]}]},
        )
    return response, mocks


def _profile(slug="resume-q-a", fabric=None):
    return SimpleNamespace(
        id=uuid4(),
        name="Resume",
        pipeline_slug=slug,
        pipeline_name="Resume pipeline" if slug else None,
        knowledge_product_id="kp",
        fabric_profile_id=fabric or uuid4(),
    )


def _version(active=True, fabric=None, number=1):
    return SimpleNamespace(
        id=uuid4(),
        version_no=number,
        is_active=active,
        description=None,
        fabric_profile_id=fabric or uuid4(),
    )


def test_unlinked_profile_is_409(client):
    response, _ = _post(client, profile=_profile(slug=None))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROFILE_NOT_LINKED"


def test_first_add_creates_the_dataset_and_writes_a_snapshot(client):
    profile = _profile()
    response, m = _post(client, profile=profile)
    assert response.status_code == 200, response.text
    assert response.json()["added"] == 1

    create = m.eval_repo.create_dataset.call_args.kwargs
    assert create["profile_id"] == profile.fabric_profile_id
    assert create["kind"] == "single_turn"
    m.snapshot.assert_awaited_once()
    # The created dataset has no fabric profile of its own, so the profile id names the object.
    assert m.snapshot.await_args.kwargs["profile_id"] == profile.id
    assert m.snapshot.await_args.kwargs["kind"] == "single_turn"
    assert m.eval_repo.add_dataset_item.call_count == 1


def test_append_reuses_the_existing_dataset(client):
    target = _dataset(filename="resume.csv", key="datasets/x/single_turn/resume.csv")
    response, m = _post(client, profile=_profile(), target=target)
    assert response.status_code == 200, response.text
    m.eval_repo.create_dataset.assert_not_called()
    assert m.snapshot.await_args.args[3] is target


def test_a_session_already_in_the_dataset_is_skipped(client):
    target = _dataset(filename="resume.csv", key="datasets/x/single_turn/resume.csv")
    response, m = _post(client, profile=_profile(), target=target, seen={"sess"})
    body = response.json()
    assert response.status_code == 200
    assert body["added"] == 0
    assert body["skipped"][0]["reason"] == "already_added"
    m.snapshot.assert_not_awaited()


def test_nothing_valid_on_an_empty_profile_is_422_and_creates_nothing(client):
    response, m = _post(client, profile=_profile(), turns=[])
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NOTHING_TO_ADD"
    m.eval_repo.create_dataset.assert_not_called()
    m.snapshot.assert_not_awaited()


def test_multi_turn_row_stores_user_turns(client):
    response, m = _post(
        client, profile=_profile(), kind="multi_turn", turns=[_turn(1), _turn(2)]
    )
    assert response.status_code == 200, response.text
    added = m.eval_repo.add_dataset_item.call_args.kwargs
    assert added["turns"] == [{"role": "user", "content": "q1"}, {"role": "user", "content": "q2"}]
    assert added["question"] == "q2"


def test_profile_without_an_active_version_is_409(client):
    response, _ = _post(client, profile=_profile(), version=_version(active=False))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "NO_ACTIVE_VERSION"
