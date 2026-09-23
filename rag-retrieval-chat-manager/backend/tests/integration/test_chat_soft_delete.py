"""Soft delete for a conversation, and for one question-and-reply turn.

These need a real database, so they skip unless DATABASE_URL is set, the same
way the Qdrant integration test skips without QDRANT_URL.

The bug these cover: both delete routes existed and the UI called them, but the
repository methods and the ``deleted_at`` columns were never added, so every
delete answered 500 and nothing could be removed from the chat history.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set; skipping integration test",
)

from rag_db.models.chat import ChatMessage, ChatSession  # noqa: E402
from rag_db.repositories.chat_repository import ChatRepository  # noqa: E402
from rag_db.services.database import get_session_factory  # noqa: E402
from rag_shared.config import get_settings  # noqa: E402


@pytest.fixture()
def repo():
    factory = get_session_factory(get_settings())
    with factory() as db:
        yield ChatRepository(db), db


def _conversation(repo: ChatRepository, db, tag: str):
    """A conversation with one question and one reply, so a turn can be removed."""
    session = repo.create_session(source_type="test", source_id=tag)
    question = repo.add_message(session.id, "user", f"question {tag}")
    reply = repo.add_message(session.id, "assistant", f"answer {tag}")
    db.commit()
    return session.id, question.id, reply.id


def _cleanup(db, *session_ids):
    """Remove the fixtures outright: the feature under test only hides rows."""
    for sid in session_ids:
        db.query(ChatMessage).filter(ChatMessage.session_id == sid).delete()
        db.query(ChatSession).filter(ChatSession.id == sid).delete()
    db.commit()


def _listed_sessions(db) -> set:
    return {str(row[0].id) for row in ChatRepository(db).list_sessions(limit=200)}


def test_soft_delete_session_hides_it_and_says_so(repo):
    repository, db = repo
    sid, _, _ = _conversation(repository, db, "session-delete")
    try:
        assert str(sid) in _listed_sessions(db), "a new conversation should be listed"

        assert repository.soft_delete_session(sid) is True
        db.commit()
        assert str(sid) not in _listed_sessions(db)

        # A second delete reports "not found" rather than succeeding twice.
        assert repository.soft_delete_session(sid) is False
    finally:
        _cleanup(db, sid)


def test_soft_delete_session_reports_an_unknown_id(repo):
    repository, _ = repo
    assert repository.soft_delete_session(uuid.uuid4()) is False


def test_soft_delete_session_also_hides_its_turns(repo):
    """A listing that starts from messages must agree with one from sessions."""
    repository, db = repo
    sid, _, _ = _conversation(repository, db, "session-turns")
    try:
        assert repository.soft_delete_session(sid) is True
        db.commit()
        assert repository.list_session_messages(sid) == []
    finally:
        _cleanup(db, sid)


def test_soft_delete_message_turn_removes_both_halves(repo):
    repository, db = repo
    sid, question_id, reply_id = _conversation(repository, db, "turn-delete")
    try:
        hidden = repository.soft_delete_message_turn(reply_id)
        db.commit()

        assert hidden is not None
        # Removing a reply must not leave its question behind.
        assert set(hidden) == {reply_id, question_id}
        assert repository.list_session_messages(sid) == []
    finally:
        _cleanup(db, sid)


def test_soft_delete_message_turn_on_a_question_removes_its_reply(repo):
    repository, db = repo
    sid, question_id, reply_id = _conversation(repository, db, "turn-delete-question")
    try:
        hidden = repository.soft_delete_message_turn(question_id)
        db.commit()

        assert hidden is not None
        assert set(hidden) == {question_id, reply_id}
    finally:
        _cleanup(db, sid)


def test_soft_delete_message_turn_reports_unknown_and_repeat(repo):
    repository, db = repo
    assert repository.soft_delete_message_turn(uuid.uuid4()) is None

    sid, _, reply_id = _conversation(repository, db, "turn-repeat")
    try:
        assert repository.soft_delete_message_turn(reply_id) is not None
        db.commit()
        assert repository.soft_delete_message_turn(reply_id) is None
    finally:
        _cleanup(db, sid)
