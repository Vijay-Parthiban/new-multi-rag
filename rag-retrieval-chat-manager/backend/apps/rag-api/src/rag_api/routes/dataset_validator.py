"""Dataset Validator: validate a dataset profile against a pipeline's collected turns.

A profile of either author, synthetic or manual, links to one RAG pipeline. The page works on
the profile's ACTIVE version only: its single-turn and multi-turn datasets are what the
validator shows and what a collected conversation is appended to.

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
from rag_api.routes.synthetic_datasets import ProfileRead, _profile_to_read

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dataset-validator", tags=["dataset-validator"])

Kind = Literal["single_turn", "multi_turn"]

KIND_LABEL: dict[str, str] = {"single_turn": "single-turn", "multi_turn": "multi-turn"}


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


class PipelineLink(BaseModel):
    """The pipeline whose conversations this profile validates. A null slug unlinks."""

    pipeline_slug: str | None = Field(default=None, max_length=128)
    pipeline_name: str | None = Field(default=None, max_length=256)


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
        metadata["evolutions"] = [row.question_type.strip()]

    if kind == "multi_turn":
        # One answer per user turn, in order: the drawer pairs them by index. The graded
        # turn takes the row's ground truth, which is the value the user approved or
        # edited. A refusal row keeps no answer; the reply it aims at is a refusal.
        expected = [
            {"content": (answer or "") if index == k - 1 else (turn.answer or "").strip()}
            for index, turn in enumerate(turns[:k])
        ]
        if answer is not None and any(entry["content"] for entry in expected):
            metadata["expected_turns"] = expected

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


def _profile(db, repo, profile_id: uuid.UUID):
    profile = repo.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Dataset profile not found.")
    return profile


def _require_pipeline(profile) -> str:
    if not profile.pipeline_slug:
        raise HTTPException(
            status_code=409,
            detail={"code": "PROFILE_NOT_LINKED", "message": "Link this profile to a pipeline first."},
        )
    return profile.pipeline_slug


def _active_version(repo, profile):
    version = next((v for v in repo.list_versions(profile.id) if v.is_active), None)
    if version is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NO_ACTIVE_VERSION",
                "message": "Set a version of this profile active before you validate it.",
            },
        )
    return version


def _target(repo, version, kind: str):
    """The dataset of this kind inside the active version, or None."""
    return next(
        (dataset for dataset in repo.datasets_for_version(version.id) if dataset.kind == kind),
        None,
    )


# ── Routes ─────────────────────────────────────────────────────────────────


@router.put("/profiles/{profile_id}/pipeline", response_model=ProfileRead)
def link_pipeline(
    request: Request, profile_id: uuid.UUID, body: PipelineLink
) -> ProfileRead:
    """Link or unlink the pipeline whose conversations this profile validates."""
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _profile(db, repo, profile_id)
        slug = (body.pipeline_slug or "").strip() or None
        profile.pipeline_slug = slug
        profile.pipeline_name = ((body.pipeline_name or "").strip() or None) if slug else None
        db.commit()
        return _profile_to_read(repo, profile)


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
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    with _session_factory(_settings(request))() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _profile(db, repo, profile_id)
        slug = _require_pipeline(profile)
        version = _active_version(repo, profile)
        target = _target(repo, version, kind)
        added = EvaluationRepository(db).source_session_ids(target.id) if target else set()
        items, total = ConversationTurnRepository(db).list_conversations(
            pipeline_slug=slug,
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
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    with _session_factory(_settings(request))() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _profile(db, repo, profile_id)
        slug = _require_pipeline(profile)
        turns_repo = ConversationTurnRepository(db)
        turns = turns_repo.get_conversation(pipeline_slug=slug, session_id=session_id)
        if not turns:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        sources = turns_repo.sources_by_message([t.message_id for t in turns if t.message_id])
        eval_repo = EvaluationRepository(db)
        added = any(
            session_id in eval_repo.source_session_ids(dataset.id)
            for dataset in repo.datasets_for_version(_active_version(repo, profile).id)
        )
        return ConversationDetail(
            session_id=session_id,
            pipeline_slug=slug,
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
    """Add the chosen conversations to the active version's dataset of this kind.

    The dataset is created on the first add, so a version that holds only one kind can
    still gain the other from a trace.
    """
    from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository
    from rag_db.repositories.evaluation_repository import EvaluationRepository
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    settings = _settings(request)
    kind = body.kind
    added_at = datetime.now(timezone.utc)

    with _session_factory(settings)() as db:
        repo = SyntheticDatasetRepository(db)
        profile = _profile(db, repo, profile_id)
        slug = _require_pipeline(profile)
        version = _active_version(repo, profile)
        turns_repo = ConversationTurnRepository(db)
        eval_repo = EvaluationRepository(db)
        target = _target(repo, version, kind)
        seen = eval_repo.source_session_ids(target.id) if target else set()

        items: list[dict[str, Any]] = []
        skipped: list[SkippedRow] = []
        for row in body.rows:
            turns = turns_repo.get_conversation(pipeline_slug=slug, session_id=row.session_id)
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
            dataset = eval_repo.create_dataset(
                f"{profile.name} v{version.version_no} · {KIND_LABEL[kind]}",
                description=version.description,
                kind=kind,
                profile_id=profile.fabric_profile_id or version.fabric_profile_id,
                row_count=0,
            )
            dataset.version_id = version.id
        else:
            dataset = target

        for item in items:
            eval_repo.add_dataset_item(dataset.id, **item)

        await store_snapshot(
            settings,
            db,
            eval_repo,
            dataset,
            profile_id=profile.id,
            kind=kind,
            kp_id=profile.knowledge_product_id,
            version_no=version.version_no,
        )
        repo.update_version(
            version.id,
            **(
                {"row_count_single": dataset.row_count}
                if kind == "single_turn"
                else {"row_count_multi": dataset.row_count}
            ),
        )
        db.commit()
        return AppendRowsResponse(dataset=_dataset_to_read(dataset), added=len(items), skipped=skipped)
