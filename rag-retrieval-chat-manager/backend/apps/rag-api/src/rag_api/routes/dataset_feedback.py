"""Dataset Feedback: turn real conversations of a pipeline into golden dataset rows.

The conversations come from `conversation_turns`, which the OpenTelemetry Collector fills
(see `routes/otlp.py`). The server builds every row from the stored turns, so the client
never sends question text. A dataset that gains rows is written back to MinIO as one
canonical JSONL file, so the file and the database rows stay the same.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from eval_core.dataset_schema import GoldenDatasetItemPayload
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from rag_api.routes.dataset_profiles import (
    DatasetFileRead,
    _dataset_to_read,
    _session_factory,
    _settings,
    store_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dataset-feedback", tags=["dataset-feedback"])

Kind = Literal["single_turn", "multi_turn"]


# ── Request and response models ────────────────────────────────────────────


class FeedbackRow(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    graded_turn: int | None = Field(default=None, ge=2)  # multi-turn only, 1-based
    ground_truth_answer: str | None = Field(default=None, max_length=20_000)
    expected_sources: list[str] = Field(default_factory=list, max_length=20)
    question_type: str | None = Field(default=None, max_length=64)
    expected_behavior: Literal["answer_from_corpus", "refuse_or_abstain"] = "answer_from_corpus"


class AppendRowsRequest(BaseModel):
    kind: Kind
    rows: list[FeedbackRow] = Field(min_length=1, max_length=50)


class SkippedRow(BaseModel):
    session_id: str
    reason: str
    detail: str = ""


class AppendRowsResponse(BaseModel):
    dataset: DatasetFileRead
    added: int
    skipped: list[SkippedRow] = Field(default_factory=list)


class ConversationItem(BaseModel):
    session_id: str
    turns: int
    trace_modes: list[str]
    first_question: str
    first_at: datetime
    last_at: datetime
    added: bool


class ConversationList(BaseModel):
    items: list[ConversationItem]
    total: int


class SourceRead(BaseModel):
    name: str
    rerank_score: float | None = None


class TurnRead(BaseModel):
    index: int
    trace_id: str
    span_id: str
    question: str
    answer: str
    trace_mode: str
    started_at: datetime
    sources: list[SourceRead] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    session_id: str
    pipeline_slug: str
    added: bool
    turns: list[TurnRead]


# ── Row building ───────────────────────────────────────────────────────────


class RowRejected(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def build_item(kind: str, turns: list, row: FeedbackRow, added_at: datetime) -> dict[str, Any]:
    """One dataset row from the stored turns of a session. Raises `RowRejected`."""
    if kind == "single_turn":
        if len(turns) != 1:
            raise RowRejected("wrong_kind")
        graded = turns[0]
        question = graded.question
        item_turns = None
    else:
        if len(turns) < 2:
            raise RowRejected("wrong_kind")
        k = row.graded_turn or len(turns)
        if not 2 <= k <= len(turns):
            raise RowRejected("wrong_kind")
        graded = turns[k - 1]
        # User turns only: the runner replays the user turns and skips the rest.
        item_turns = [{"role": "user", "content": t.question} for t in turns[:k]]
        question = item_turns[-1]["content"]

    if row.expected_behavior == "refuse_or_abstain":
        answer, sources = None, []
    else:
        answer = (row.ground_truth_answer or "").strip()
        if not answer:
            raise RowRejected("answer_required")
        sources = list(dict.fromkeys(s.strip() for s in row.expected_sources if s.strip()))

    metadata: dict[str, Any] = {
        "expected_behavior": row.expected_behavior,
        "source": "dataset_feedback",
        "source_session_id": row.session_id,
        "source_trace_id": graded.trace_id,
        "source_span_id": graded.span_id,
        "trace_mode": graded.trace_mode,
        "added_at": added_at.isoformat(),
    }
    if (row.question_type or "").strip():
        metadata["question_type"] = row.question_type.strip()

    try:
        GoldenDatasetItemPayload.model_validate(
            {
                "question": question,
                "ground_truth_answer": answer,
                "expected_sources": [{"name": n} for n in sources],
                "turns": item_turns,
                "metadata": metadata,
            }
        )
    except ValidationError as exc:
        raise RowRejected("invalid_row", str(exc)) from exc
    return {
        "question": question,
        "ground_truth_answer": answer,
        "expected_sources": [{"name": n} for n in sources],
        "turns": item_turns,
        "metadata": metadata,
    }


# ── Helpers ────────────────────────────────────────────────────────────────


def _linked_profile(db, profile_id: uuid.UUID):
    from rag_db.repositories.dataset_profile_repository import DatasetProfileRepository

    profile = DatasetProfileRepository(db).get(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Dataset profile not found.")
    if not profile.pipeline_slug:
        raise HTTPException(
            status_code=409,
            detail={"code": "PROFILE_NOT_LINKED", "message": "Link this profile to a pipeline first."},
        )
    return profile


def _target(profile, kind: str):
    """The newest dataset of this kind: the one Offline Evaluation runs."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return max(
        (d for d in profile.datasets or [] if d.kind == kind),
        key=lambda d: d.created_at or floor,
        default=None,
    )


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/profiles/{profile_id}/conversations", response_model=ConversationList)
def list_conversations(
    request: Request,
    profile_id: uuid.UUID,
    kind: Kind,
    mode: Literal["all", "test", "prod"] = "all",
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ConversationList:
    from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    with _session_factory(_settings(request))() as db:
        profile = _linked_profile(db, profile_id)
        target = _target(profile, kind)
        added = EvaluationRepository(db).source_session_ids(target.id) if target else set()
        items, total = ConversationTurnRepository(db).list_conversations(
            pipeline_slug=profile.pipeline_slug,
            kind=kind,
            mode=mode,
            q=(q or "").strip() or None,
            limit=limit,
            offset=offset,
        )
        return ConversationList(
            items=[ConversationItem(**i, added=i["session_id"] in added) for i in items],
            total=total,
        )


@router.get("/profiles/{profile_id}/conversations/{session_id}", response_model=ConversationDetail)
def get_conversation(request: Request, profile_id: uuid.UUID, session_id: str) -> ConversationDetail:
    from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    with _session_factory(_settings(request))() as db:
        profile = _linked_profile(db, profile_id)
        repo = ConversationTurnRepository(db)
        turns = repo.get_conversation(pipeline_slug=profile.pipeline_slug, session_id=session_id)
        if not turns:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        sources = repo.sources_by_message([t.message_id for t in turns if t.message_id])
        added = any(
            session_id in EvaluationRepository(db).source_session_ids(d.id)
            for d in profile.datasets or []
        )
        return ConversationDetail(
            session_id=session_id,
            pipeline_slug=profile.pipeline_slug,
            added=added,
            turns=[
                TurnRead(
                    index=n,
                    trace_id=t.trace_id,
                    span_id=t.span_id,
                    question=t.question,
                    answer=t.answer,
                    trace_mode=t.trace_mode,
                    started_at=t.started_at,
                    sources=[SourceRead(**s) for s in sources.get(t.message_id, [])],
                )
                for n, t in enumerate(turns, start=1)
            ],
        )


@router.post("/profiles/{profile_id}/rows", response_model=AppendRowsResponse)
async def append_rows(
    request: Request, profile_id: uuid.UUID, body: AppendRowsRequest
) -> AppendRowsResponse:
    """Add the chosen conversations as rows, creating the dataset on the first add."""
    from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository

    settings = _settings(request)
    kind = body.kind
    added_at = datetime.now(timezone.utc)

    with _session_factory(settings)() as db:
        profile = _linked_profile(db, profile_id)
        turns_repo = ConversationTurnRepository(db)
        repo = EvaluationRepository(db)
        target = _target(profile, kind)
        seen = repo.source_session_ids(target.id) if target else set()

        items: list[dict[str, Any]] = []
        skipped: list[SkippedRow] = []
        for row in body.rows:
            turns = turns_repo.get_conversation(
                pipeline_slug=profile.pipeline_slug, session_id=row.session_id
            )
            if not turns:
                skipped.append(SkippedRow(session_id=row.session_id, reason="conversation_not_found"))
                continue
            if row.session_id in seen:
                skipped.append(SkippedRow(session_id=row.session_id, reason="already_added"))
                continue
            try:
                items.append(build_item(kind, turns, row, added_at))
            except RowRejected as exc:
                skipped.append(SkippedRow(session_id=row.session_id, reason=exc.reason, detail=exc.detail))
                continue
            seen.add(row.session_id)

        if not items:
            if target is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "NOTHING_TO_ADD",
                        "message": "None of the selected conversations could be added.",
                    },
                )
            return AppendRowsResponse(dataset=_dataset_to_read(target), added=0, skipped=skipped)

        if target is None:
            dataset = repo.create_dataset(
                f"{profile.name}::{kind}::{uuid.uuid4().hex[:6]}",
                description=f"Collected from {profile.pipeline_slug} conversations",
                kind=kind,
                profile_id=profile.id,
                row_count=0,
            )
        else:
            dataset = target

        for item in items:
            repo.add_dataset_item(dataset.id, **item)

        await store_snapshot(settings, db, repo, dataset, profile_id=profile.id, kind=kind)
        return AppendRowsResponse(dataset=_dataset_to_read(dataset), added=len(items), skipped=skipped)
