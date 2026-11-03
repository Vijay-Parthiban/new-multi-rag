from __future__ import annotations

import gzip
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from rag_api.main import create_app
from rag_api.otlp_turns import parse_turn_spans

MESSAGE_ID = str(uuid.uuid4())


def _a(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}  # OTLP/JSON int64 is a string
    return {"key": key, "value": {"stringValue": value}}


def _span(name="rag.chat", span_id="a" * 16, **attrs):
    return {
        "traceId": "b" * 32,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": "1760000000000000000",
        "attributes": [_a(k, v) for k, v in attrs.items()],
    }


TURN = {
    "session.id": "s-1",
    "rag.pipeline.slug": "resume-q-a",
    "rag.trace_mode": "test",
    "input.value": "What is X?",
    "output.value": "X is Y.",
    "langfuse.observation.metadata.message_id": MESSAGE_ID,
    "rag.chunks_used": 4,
}


def _payload(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def test_parser_keeps_only_complete_turn_spans():
    records = parse_turn_spans(
        _payload(
            _span(**TURN),
            _span("rag.pipeline.metrics", span_id="c" * 16, **{"session.id": "s-1"}),
            _span(span_id="d" * 16, **{k: v for k, v in TURN.items() if k != "output.value"}),
        )
    )
    assert len(records) == 1
    r = records[0]
    assert (r["pipeline_slug"], r["trace_mode"], r["session_id"]) == ("resume-q-a", "test", "s-1")
    assert (r["question"], r["answer"]) == ("What is X?", "X is Y.")
    assert r["message_id"] == uuid.UUID(MESSAGE_ID)
    assert r["chunks_used"] == 4  # the string intValue is cast
    assert r["blocked"] is False
    assert r["trace_id"] == "b" * 32 and r["span_id"] == "a" * 16


def test_parser_flags_a_guardrail_block_and_defaults_the_mode_to_prod():
    attrs = {**TURN, "guardrails.input.blocked": True}
    attrs.pop("rag.trace_mode")
    (r,) = parse_turn_spans(_payload(_span(**attrs)))
    assert r["blocked"] is True
    assert r["trace_mode"] == "prod"


@pytest.fixture
def client():
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


def _post(client, body: bytes, **headers):
    return client.post("/otlp/v1/traces", content=body, headers=headers)


def _store(repo):
    return (
        patch("rag_db.services.database.get_session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.conversation_turn_repository.ConversationTurnRepository",
            return_value=repo,
        ),
    )


def test_gzip_body_is_stored(client):
    repo = MagicMock()
    body = gzip.compress(json.dumps(_payload(_span(**TURN))).encode())
    p1, p2 = _store(repo)
    with p1, p2:
        response = _post(client, body, **{"Content-Type": "application/json", "Content-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.json() == {"partialSuccess": {}}
    repo.insert_turns.assert_called_once()
    assert repo.insert_turns.call_args.args[0][0]["session_id"] == "s-1"


def test_batch_without_turns_stores_nothing(client):
    repo = MagicMock()
    p1, p2 = _store(repo)
    with p1, p2:
        response = _post(
            client,
            json.dumps(_payload(_span("rag.pipeline.metrics"))).encode(),
            **{"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    repo.insert_turns.assert_not_called()


def test_invalid_json_is_400(client):
    assert _post(client, b"{nope", **{"Content-Type": "application/json"}).status_code == 400


def test_protobuf_is_415(client):
    response = _post(client, b"\x0a\x00", **{"Content-Type": "application/x-protobuf"})
    assert response.status_code == 415
    assert "encoding: json" in response.json()["detail"]


def test_oversized_body_is_413(client):
    body = b" " * (5 * 1024 * 1024 + 1)
    assert _post(client, body, **{"Content-Type": "application/json"}).status_code == 413


def test_store_failure_is_503_so_the_collector_retries(client):
    repo = MagicMock()
    repo.insert_turns.side_effect = SQLAlchemyError("down")
    p1, p2 = _store(repo)
    with p1, p2:
        response = _post(
            client, json.dumps(_payload(_span(**TURN))).encode(), **{"Content-Type": "application/json"}
        )
    assert response.status_code == 503
