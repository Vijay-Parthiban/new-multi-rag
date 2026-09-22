"""Session memory behaviour.

The logic worth testing is the LTRIM bound, the TTL refresh, the decode of a
corrupt entry and the fail-soft read. A fake Redis would have to reimplement all
four, and Redis is already running for the rest of the suite, so these tests use
the real thing and skip when it is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from rag_core.schemas import SessionTurn
from rag_core.session_memory import SessionMemory, memory_key
from rag_shared.config import Settings

REDIS_URL = "redis://localhost:6379/0"


def _client_or_skip():
    import redis

    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis is not reachable: {exc}")
    return client


@pytest.fixture()
def memory():
    client = _client_or_skip()
    prefix = f"test:session:{uuid.uuid4().hex[:8]}"
    # Two turns means four messages, which makes the trim observable in three.
    mem = SessionMemory(Settings(redis_url=REDIS_URL), prefix=prefix, max_turns=2, ttl_s=120)
    yield mem
    for key in client.scan_iter(match=f"{prefix}:memory:*"):
        client.delete(key)


def _turns(*pairs: tuple[str, str]) -> list[SessionTurn]:
    out: list[SessionTurn] = []
    for question, answer in pairs:
        out.append(SessionTurn(role="user", content=question))
        out.append(SessionTurn(role="assistant", content=answer))
    return out


def test_memory_key_is_namespaced_by_prefix() -> None:
    assert memory_key("kp:demo:abc12345", "s-1") == "kp:demo:abc12345:memory:s-1"


def test_missing_session_loads_empty(memory: SessionMemory) -> None:
    assert memory.load(str(uuid.uuid4())) == []


def test_append_then_load_round_trips_in_order(memory: SessionMemory) -> None:
    session = str(uuid.uuid4())
    memory.append(session, _turns(("Who is the candidate?", "Alice Smith.")))

    turns = memory.load(session)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[0].content == "Who is the candidate?"
    assert turns[1].content == "Alice Smith."


def test_trim_keeps_only_the_newest_turns(memory: SessionMemory) -> None:
    session = str(uuid.uuid4())
    memory.append(session, _turns(("q1", "a1")))
    memory.append(session, _turns(("q2", "a2")))
    memory.append(session, _turns(("q3", "a3")))

    contents = [t.content for t in memory.load(session)]
    # max_turns=2, so the oldest pair is gone and the two newest remain in order.
    assert contents == ["q2", "a2", "q3", "a3"]


def test_every_write_refreshes_the_ttl(memory: SessionMemory) -> None:
    session = str(uuid.uuid4())
    memory.append(session, _turns(("q", "a")))

    import redis

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    ttl = client.ttl(memory.key_for(session))
    assert 0 < ttl <= 120


def test_clear_removes_the_session_and_is_idempotent(memory: SessionMemory) -> None:
    session = str(uuid.uuid4())
    memory.append(session, _turns(("q", "a")))

    assert memory.clear(session) is True
    assert memory.load(session) == []
    # Ending a session twice, or ending one that already expired, is not an error.
    assert memory.clear(session) is False


def test_clear_leaves_other_sessions_alone(memory: SessionMemory) -> None:
    keep = str(uuid.uuid4())
    drop = str(uuid.uuid4())
    memory.append(keep, _turns(("keep", "yes")))
    memory.append(drop, _turns(("drop", "no")))

    memory.clear(drop)
    assert [t.content for t in memory.load(keep)] == ["keep", "yes"]


def test_inspect_reports_turns_and_ttl(memory: SessionMemory) -> None:
    session = str(uuid.uuid4())
    memory.append(session, _turns(("q", "a")))

    report = memory.inspect(session)
    assert report["exists"] is True
    assert report["turns"] == 2
    assert report["ttl_seconds"] is not None and report["ttl_seconds"] > 0
    assert [t["role"] for t in report["history"]] == ["user", "assistant"]


def test_inspect_on_a_missing_session(memory: SessionMemory) -> None:
    report = memory.inspect(str(uuid.uuid4()))
    assert report["exists"] is False
    assert report["turns"] == 0
    assert report["ttl_seconds"] is None


def test_a_corrupt_entry_is_skipped_not_raised(memory: SessionMemory) -> None:
    import json

    import redis

    session = str(uuid.uuid4())
    memory.append(session, _turns(("good", "answer")))

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    key = memory.key_for(session)
    # A truncated payload and a valid JSON object with the wrong shape.
    client.rpush(key, "{not json")
    client.rpush(key, json.dumps({"role": "system", "content": "not a remembered role"}))

    turns = memory.load(session)
    assert [t.content for t in turns] == ["good", "answer"]


def test_a_read_failure_is_soft(memory: SessionMemory, monkeypatch) -> None:
    """A Redis outage makes the assistant stateless; it must not fail the turn."""

    def _boom(_url: str):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("rag_core.session_memory._client", _boom)
    assert memory.load(str(uuid.uuid4())) == []


def test_a_write_failure_is_soft(memory: SessionMemory, monkeypatch) -> None:
    def _boom(_url: str):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("rag_core.session_memory._client", _boom)
    # Must not raise, and must not leave a partial entry behind.
    memory.append(str(uuid.uuid4()), _turns(("q", "a")))


def test_clear_raises_when_redis_is_down(memory: SessionMemory, monkeypatch) -> None:
    """Ending a session is the one operation a caller must know failed."""
    from rag_core.session_memory import SessionMemoryUnavailable

    def _boom(_url: str):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("rag_core.session_memory._client", _boom)
    with pytest.raises(SessionMemoryUnavailable):
        memory.clear(str(uuid.uuid4()))
