"""Ending a conversation, for both the Chat page and the pipeline endpoint.

Two routes end a session: the native chat route, which the Chat page calls, and the assistant
route, which is the production path an integrating project calls. The steps are not optional —
write the conversation out as one trace, then drop what the pipeline remembered — so they live
here rather than in two copies that would drift.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from rag_api.trace_context import fetch_context, memory_for_pipeline
from rag_core.session_memory import SessionMemory, SessionMemoryUnavailable
from rag_db.repositories.chat_repository import ChatRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings
from rag_shared.tracing import emit_session_trace, turn_tags

logger = logging.getLogger(__name__)


class SessionNotFound(LookupError):
    """The session id is unknown, so there is nothing to end."""


def message_order(row: Any) -> tuple[int, Any, int]:
    """Sort key for one message row: time first, then the question before its reply.

    `created_at` is absent on some rows, so its presence is the first component. That keeps a
    missing timestamp from ever being compared against a real one.
    """
    message = row[0]
    created = getattr(message, "created_at", None)
    return (1 if created is not None else 0, created or 0, 0 if message.role == "user" else 1)


def qa_pairs(rows: list[Any]) -> list[tuple[str, str]]:
    """Pair each question with the reply that follows it.

    The order is made deterministic rather than trusted. The two rows of one turn are written
    in the same transaction, so they carry the same timestamp, and a plain time ordering can
    return the reply before the question it answers. A question therefore sorts before a reply
    at the same instant, which is the same tie-break the Chat page applies when it displays a
    conversation.

    A question with no reply yet is dropped: there is nothing to export for it.
    """
    pairs: list[tuple[str, str]] = []
    question: str | None = None
    for message, _trace, _metrics in sorted(rows, key=message_order):
        if message.role == "user":
            question = message.content
        elif message.role == "assistant" and question is not None:
            pairs.append((question, message.content))
            question = None
    return pairs


def close_session(
    settings: Settings,
    session_id: uuid.UUID,
    *,
    pipeline_id: str | None,
    trace_mode: str,
) -> dict[str, Any]:
    """Export the conversation as one trace, then drop what it remembered.

    Only a pipeline with session memory gets a session trace, because only it kept a
    conversation to export. A stateless pipeline already traced each turn on its own, so there
    is nothing to group and nothing to clear.

    The export is best effort and the memory is dropped either way. The caller asked to end the
    session, and a key that outlives the conversation is worse than a missing trace.
    """
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = ChatRepository(db)
        if not repo.get_session(session_id):
            raise SessionNotFound(str(session_id))
        rows = repo.list_session_messages(session_id)

    turns = qa_pairs(rows)
    memory = memory_for_pipeline(settings, pipeline_id)
    tags = turn_tags(trace_mode, memory is not None)

    cleared = False
    if memory:
        try:
            cleared = SessionMemory(settings, prefix=memory[0], ttl_s=memory[1]).clear(
                str(session_id)
            )
        except SessionMemoryUnavailable as exc:
            logger.warning("close session: redis refused session=%s error=%s", session_id, exc)
        except Exception as exc:  # noqa: BLE001 - ending must not leave the key behind silently
            logger.warning("close session: clear failed session=%s error=%s", session_id, exc)

    trace_id: str | None = None
    if memory:
        trace_id, _ = emit_session_trace(
            session_id=str(session_id),
            turns=turns,
            trace_mode=trace_mode,
            tags=tags,
            attributes=fetch_context(settings, pipeline_id),
        )

    return {
        "session_id": str(session_id),
        "turns": len(turns),
        "memory": {"enabled": memory is not None, "cleared": cleared},
        "trace": {
            "emitted": memory is not None,
            "trace_id": trace_id,
            "tags": tags,
        },
    }
