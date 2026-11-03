"""Reads and writes for the turns the OpenTelemetry Collector delivered."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rag_db.models.chat import ChatMessage, ChatPipelineTrace
from rag_db.models.conversation_turn import ConversationTurn


def _visible(slug: str):
    """Turns of one pipeline that are real conversation.

    A blocked turn is not conversation (the app already refuses to keep it in memory),
    and a turn whose chat message the user deleted must not come back here.
    """
    deleted = exists().where(
        ChatMessage.id == ConversationTurn.message_id, ChatMessage.deleted_at.is_not(None)
    )
    return and_(
        ConversationTurn.pipeline_slug == slug,
        ConversationTurn.blocked.is_(False),
        ~deleted,
    )


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class ConversationTurnRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_turns(self, records: list[dict[str, Any]]) -> int:
        """Store turns. A repeated `(trace_id, span_id)` is ignored, so retries are safe."""
        if not records:
            return 0
        stmt = (
            insert(ConversationTurn)
            .values(records)
            .on_conflict_do_nothing(index_elements=["trace_id", "span_id"])
            .returning(ConversationTurn.id)
        )
        return len(self._session.execute(stmt).all())

    def list_conversations(
        self,
        *,
        pipeline_slug: str,
        kind: str,
        mode: str = "all",
        q: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Sessions of one pipeline, newest first, with their turn count.

        A session is classified by its full turn count, so the mode and text filters sit in
        HAVING, not WHERE: a one-turn session stays one turn however it is filtered.
        """
        turns = func.count()
        grouped = (
            select(
                ConversationTurn.session_id,
                turns.label("turns"),
                func.min(ConversationTurn.started_at).label("first_at"),
                func.max(ConversationTurn.started_at).label("last_at"),
                func.array_agg(func.distinct(ConversationTurn.trace_mode)).label("modes"),
            )
            .where(_visible(pipeline_slug))
            .group_by(ConversationTurn.session_id)
            .having(turns == 1 if kind == "single_turn" else turns >= 2)
        )
        if mode in ("test", "prod"):
            grouped = grouped.having(func.bool_or(ConversationTurn.trace_mode == mode))
        if q:
            grouped = grouped.having(
                func.bool_or(ConversationTurn.question.ilike(_like(q), escape="\\"))
            )

        total = self._session.execute(
            select(func.count()).select_from(grouped.subquery())
        ).scalar_one()
        rows = self._session.execute(
            grouped.order_by(func.max(ConversationTurn.started_at).desc(), ConversationTurn.session_id)
            .limit(limit)
            .offset(offset)
        ).all()
        if not rows:
            return [], total

        first_question: dict[str, str] = {}
        for session_id, question in self._session.execute(
            select(ConversationTurn.session_id, ConversationTurn.question)
            .where(_visible(pipeline_slug), ConversationTurn.session_id.in_([r.session_id for r in rows]))
            .order_by(ConversationTurn.started_at, ConversationTurn.created_at)
        ):
            first_question.setdefault(session_id, question)

        return [
            {
                "session_id": r.session_id,
                "turns": r.turns,
                "trace_modes": sorted(r.modes),
                "first_question": first_question.get(r.session_id, ""),
                "first_at": r.first_at,
                "last_at": r.last_at,
            }
            for r in rows
        ], total

    def get_conversation(self, *, pipeline_slug: str, session_id: str) -> list[ConversationTurn]:
        return list(
            self._session.scalars(
                select(ConversationTurn)
                .where(_visible(pipeline_slug), ConversationTurn.session_id == session_id)
                .order_by(ConversationTurn.started_at, ConversationTurn.created_at)
            )
        )

    def sources_by_message(self, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
        """The documents behind each reply: best rerank score per file name, top eight."""
        if not message_ids:
            return {}
        out: dict[uuid.UUID, list[dict]] = {}
        for message_id, chunks in self._session.execute(
            select(ChatPipelineTrace.chat_message_id, ChatPipelineTrace.reranked_chunks).where(
                ChatPipelineTrace.chat_message_id.in_(message_ids)
            )
        ):
            best: dict[str, float | None] = {}
            for chunk in chunks or []:
                locator = str(chunk.get("source_locator") or "")
                name = locator.rstrip("/").rsplit("/", 1)[-1] or locator
                if not name:
                    continue
                score = chunk.get("rerank_score")
                previous = best.get(name)
                if name not in best or (score is not None and (previous is None or score > previous)):
                    best[name] = score
            ranked = sorted(best.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0)))
            out[message_id] = [{"name": n, "rerank_score": s} for n, s in ranked[:8]]
        return out
