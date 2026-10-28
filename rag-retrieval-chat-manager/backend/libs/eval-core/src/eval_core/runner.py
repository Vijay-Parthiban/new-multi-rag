from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from rag_core import PipelineConfig, RAGPipeline, SessionMemory, SessionTurn
from rag_shared.chunk_utils import is_image_chunk, passage_text_for_chunk
from rag_shared.config import Settings
from rag_shared.types import RerankedChunk, RetrievedChunk

from eval_core.custom_metrics import compute_custom_metrics
from eval_core.ragas_client import compute_generation_ragas_metrics, compute_triad_metrics
from eval_core.rerank_metrics import compute_rerank_metrics
from eval_core.retrieval_metrics import compute_retrieval_metrics
from eval_core.source_match import ExpectedSource, parse_expected_sources

logger = logging.getLogger(__name__)


@dataclass
class GoldenItem:
    question: str
    ground_truth_answer: str | None
    expected_sources: list[Any]
    label: str | None = None
    category: str | None = None
    # The user turns of a conversation, in order. None on a single-turn row. `question` is
    # the last of them, which is what the generation metrics score.
    turns: list[dict[str, str]] | None = None
    # The CSV's extra columns. They drive the custom metrics and the per-category roll-up.
    metadata: dict[str, Any] = field(default_factory=dict)

    def parsed_sources(self) -> list[ExpectedSource]:
        return parse_expected_sources(self.expected_sources)


@dataclass
class EvalItemResult:
    retrieved_chunks: list[RetrievedChunk]
    retrieval_metrics: dict
    reranked_chunks: list[RerankedChunk]
    rerank_metrics: dict
    generated_answer: str
    generation_metrics: dict


class GoldenItemEvaluator:
    def __init__(self, settings: Settings, pipeline: RAGPipeline | None = None) -> None:
        self._settings = settings
        self._pipeline = pipeline or RAGPipeline(settings)

    def evaluate_item(
        self,
        item: GoldenItem,
        config: PipelineConfig,
        k_values: list[int] | None = None,
        *,
        judge_model: str | None = None,
        session_memory: SessionMemory | None = None,
    ) -> EvalItemResult:
        """Run one row through the pipeline and score the answer.

        The run goes through `RAGPipeline.chat`, which is the path a live turn takes. That is
        what makes the self-reflective and corrective strategies measurable: their grading and
        revision branches live there, and a direct retrieve → rerank → generate call never
        reached them.
        """
        if item.turns:
            result = self._run_conversation(item, config, session_memory)
        else:
            result = self._pipeline.chat(item.question, config=config)
        return self._score(result, item, k_values, judge_model)

    def _run_conversation(
        self,
        item: GoldenItem,
        config: PipelineConfig,
        memory: SessionMemory | None,
    ):
        """Replay the user turns, swapping each answer into the session's memory.

        This is the same protocol a live chat turn uses: load the session before the turn,
        append the exchange after it. The Redis path under test is therefore the production
        one. The last turn's result is what gets scored.
        """
        session_id = str(uuid.uuid4())
        last = None
        try:
            for turn in item.turns or []:
                if turn.get("role") != "user":
                    continue
                if memory is not None:
                    config.history = memory.load(session_id)
                last = self._pipeline.chat(turn["content"], config=config)
                if memory is not None:
                    memory.append(
                        session_id,
                        [
                            SessionTurn(role="user", content=turn["content"]),
                            SessionTurn(role="assistant", content=last.answer),
                        ],
                    )
        finally:
            if memory is not None:
                try:
                    memory.clear(session_id)
                except Exception:  # noqa: BLE001 - a stale key expires on its own TTL
                    logger.warning("eval session clear failed session=%s", session_id)
        if last is None:
            raise ValueError("a multi-turn row needs at least one user turn")
        return last

    def _score(
        self,
        result,
        item: GoldenItem,
        k_values: list[int] | None,
        judge_model: str | None,
    ) -> EvalItemResult:
        k_values = k_values or [1, 3, 5, 10]
        expected = item.parsed_sources()

        # Formula-based retrieval metrics only (no LLM-as-judge for IRS).
        retrieval_metrics = compute_retrieval_metrics(result.retrieved_chunks, expected, k_values)
        # The standalone question a session turn was rewritten into. It is the only record of
        # whether a follow-up reached retrieval as a pronoun or as a real question, and the
        # aggregate means skip it because it is a string.
        if getattr(result, "effective_query", None):
            retrieval_metrics["effective_query"] = result.effective_query
        rerank_metrics = compute_rerank_metrics(
            result.retrieved_chunks, result.reranked_chunks, expected, k_values
        )

        contexts = [
            passage_text_for_chunk(c) if is_image_chunk(c) else c.content
            for c in result.reranked_chunks
        ]
        generation_metrics = compute_generation_ragas_metrics(
            self._settings,
            question=item.question,
            answer=result.answer,
            contexts=contexts,
            ground_truth=item.ground_truth_answer,
            judge_model=judge_model,
            # The triad scores answer_relevancy from the same question and answer below, so
            # scoring it here too would be a second judge call for a value that is overwritten.
            include_answer_relevancy=False,
        )
        # The triad reads the retrieved contexts and the answer, so it belongs beside the
        # other generation metrics. It runs even when the dataset carries no ground truth,
        # which is what lets an unanswerable row still name a failing stage. The stage
        # reading itself is computed when a report is read, from these stored numbers, so
        # the rules can change without re-running a run.
        triad = compute_triad_metrics(
            self._settings,
            question=item.question,
            answer=result.answer,
            contexts=contexts,
            judge_model=judge_model,
        )
        generation_metrics = {**generation_metrics, **triad}
        # The dataset's own checks ride along in the same block, so the aggregate picks them
        # up with no new column and no new stage. A key is present only when the row carried
        # the input for it, so each mean covers exactly the rows that asked for it.
        generation_metrics = {
            **generation_metrics,
            **compute_custom_metrics(item.metadata, result.answer),
        }

        return EvalItemResult(
            retrieved_chunks=result.retrieved_chunks,
            retrieval_metrics=retrieval_metrics,
            reranked_chunks=result.reranked_chunks,
            rerank_metrics=rerank_metrics,
            generated_answer=result.answer,
            generation_metrics=generation_metrics,
        )
