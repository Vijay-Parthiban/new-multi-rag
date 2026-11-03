"""Conversation turns delivered by the collector: classification, filters, idempotency."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set; skipping integration test",
)

from rag_db.models.chat import ChatMessage, ChatSession  # noqa: E402
from rag_db.models.conversation_turn import ConversationTurn  # noqa: E402
from rag_db.repositories.chat_repository import ChatRepository  # noqa: E402
from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository  # noqa: E402
from rag_db.services.database import get_session_factory  # noqa: E402
from rag_shared.config import get_settings  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def env():
    slug = f"test-{uuid.uuid4().hex[:8]}"
    factory = get_session_factory(get_settings())
    with factory() as db:
        yield slug, ConversationTurnRepository(db), db
        db.rollback()
        db.query(ConversationTurn).filter(ConversationTurn.pipeline_slug == slug).delete()
        db.commit()


def _turn(slug, session, n=0, *, mode="prod", question=None, blocked=False, message_id=None, span=None):
    return {
        "trace_id": uuid.uuid4().hex,
        "span_id": span or uuid.uuid4().hex[:16],
        "session_id": session,
        "pipeline_slug": slug,
        "trace_mode": mode,
        "question": question or f"question {session} {n}",
        "answer": f"answer {session} {n}",
        "message_id": message_id,
        "blocked": blocked,
        "started_at": NOW + timedelta(seconds=n),
    }


def _ids(repo, slug, kind, **kw):
    items, total = repo.list_conversations(pipeline_slug=slug, kind=kind, **kw)
    return {i["session_id"] for i in items}, total


def test_session_is_classified_by_its_turn_count(env):
    slug, repo, db = env
    repo.insert_turns([_turn(slug, "one"), _turn(slug, "two", 0), _turn(slug, "two", 1)])
    db.commit()
    assert _ids(repo, slug, "single_turn") == ({"one"}, 1)
    assert _ids(repo, slug, "multi_turn") == ({"two"}, 1)


def test_blocked_turn_is_excluded_and_demotes_a_session(env):
    slug, repo, db = env
    repo.insert_turns([_turn(slug, "s", 0), _turn(slug, "s", 1, blocked=True)])
    db.commit()
    assert _ids(repo, slug, "single_turn")[0] == {"s"}
    assert _ids(repo, slug, "multi_turn")[0] == set()


def test_soft_deleted_message_hides_its_turn(env):
    slug, repo, db = env
    chat = ChatRepository(db)
    session = chat.create_session(source_type="test", source_id=slug)
    reply = chat.add_message(session.id, "assistant", "answer")
    db.commit()
    try:
        repo.insert_turns([_turn(slug, "gone", message_id=reply.id)])
        db.commit()
        assert _ids(repo, slug, "single_turn")[0] == {"gone"}
        reply.deleted_at = NOW
        db.commit()
        assert _ids(repo, slug, "single_turn")[0] == set()
    finally:
        db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
        db.query(ChatSession).filter(ChatSession.id == session.id).delete()
        db.commit()


def test_same_span_twice_stores_one_row(env):
    slug, repo, db = env
    record = _turn(slug, "dup")
    assert repo.insert_turns([record]) == 1
    assert repo.insert_turns([record]) == 0
    db.commit()
    assert _ids(repo, slug, "single_turn")[1] == 1


def test_mode_keeps_sessions_that_contain_that_mode(env):
    slug, repo, db = env
    repo.insert_turns(
        [_turn(slug, "t", mode="test"), _turn(slug, "p", mode="prod"), _turn(slug, "m", 0, mode="test"), _turn(slug, "m", 1, mode="prod")]
    )
    db.commit()
    assert _ids(repo, slug, "single_turn", mode="test")[0] == {"t"}
    assert _ids(repo, slug, "single_turn", mode="prod")[0] == {"p"}
    assert _ids(repo, slug, "multi_turn", mode="test")[0] == {"m"}
    assert _ids(repo, slug, "multi_turn", mode="prod")[0] == {"m"}


def test_text_search_matches_any_turn_without_changing_the_kind(env):
    slug, repo, db = env
    repo.insert_turns(
        [_turn(slug, "m", 0, question="first"), _turn(slug, "m", 1, question="needle here"), _turn(slug, "x", question="100% sure")]
    )
    db.commit()
    assert _ids(repo, slug, "multi_turn", q="needle")[0] == {"m"}
    assert _ids(repo, slug, "single_turn", q="needle")[0] == set()
    assert _ids(repo, slug, "single_turn", q="100%")[0] == {"x"}
    assert _ids(repo, slug, "single_turn", q="%")[0] == {"x"}
    assert _ids(repo, slug, "single_turn", q="nomatch")[0] == set()
