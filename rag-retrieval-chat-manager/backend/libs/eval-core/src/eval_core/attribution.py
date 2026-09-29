"""Name the stage that failed, from the scores that stage produced.

One overall score says a pipeline is bad. It does not say whether the retriever handed
over the wrong passages, the reranker buried the right one, or the generator ignored
what it was given, and those three need different fixes.

The triad reads each of them separately, so three scores name the stage:

    context_relevance low                  the retriever did not find it
    context_relevance low, recall lost     the reranker buried what was found
    context_relevance ok, groundedness low the generator invented
    both ok, answer_relevancy low          the answer is supported but off the question
    all ok                                 the turn is sound

The thresholds are the whole judgement, so they are named constants here rather than
numbers scattered through the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# A score at or above this passes. RAGAS judge metrics are noisy in the 0.6-0.8 band, so
# this sits below a "good" score on purpose: it flags the clearly broken, not the merely
# unpolished, and a pipeline that trips it has a fault worth reading the row for.
PASS_MARK = 0.7

# The reranked MRR has to fall this far below the retrieved MRR before the reranker is
# blamed. Below it the two rank the same and the retriever owns the miss.
RERANK_LOSS_MARGIN = 0.05


@dataclass(frozen=True)
class Diagnosis:
    """The stage an item's scores point at, and the evidence for that reading."""

    stage: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "reason": self.reason, "evidence": self.evidence}


# Every stage this module can name. The aggregate reports a count per stage, so the
# list is the set of keys a report can carry.
STAGES = (
    "healthy",
    "retrieval",
    "rerank",
    "generation_grounding",
    "generation_relevance",
    "unknown",
)

STAGE_LABELS = {
    "healthy": "Sound",
    "retrieval": "Retrieval",
    "rerank": "Reranker",
    "generation_grounding": "Generation — invented",
    "generation_relevance": "Generation — off the question",
    "unknown": "Not scored",
}


def _winner(
    *,
    retrieval_mrr: float | None,
    rerank_mrr: float | None,
    rerank_enabled: bool | None = True,
) -> tuple[str, str]:
    """Retrieval or rerank, whichever lost the evidence.

    The reranker is blamed only when all three hold: reranking ran, the retriever ranked the
    evidence at the same depth the reranker was judged at, and the ranking that reached the
    generator fell below it. Without all three the retriever owns the miss, because that is
    the stage the context relevance score actually measured.

    `rerank_enabled` defaults to True so a caller that does not track the setting keeps the
    previous reading rather than silently losing the rerank verdict.
    """
    if rerank_enabled is False:
        return (
            "retrieval",
            "Reranking is off for this run, so the ranking that reached the generator is the "
            "one the retriever produced. The retrieved passages do not cover the question.",
        )
    if (
        retrieval_mrr is not None
        and rerank_mrr is not None
        and rerank_mrr + RERANK_LOSS_MARGIN < retrieval_mrr
    ):
        return (
            "rerank",
            f"The retriever ranked the evidence at MRR {retrieval_mrr:.2f} within the top-k and "
            f"the reranked order kept {rerank_mrr:.2f}. The right passage arrived and the "
            "reranker moved it out of reach.",
        )
    return (
        "retrieval",
        "The retrieved passages do not cover the question. Nothing downstream can "
        "recover evidence that was never fetched.",
    )


def diagnose(
    triad: Mapping[str, float | None],
    *,
    retrieval_mrr: float | None = None,
    rerank_mrr: float | None = None,
    rerank_enabled: bool | None = True,
) -> Diagnosis:
    """Read the triad and name the stage.

    A missing score is not a zero. When a judge call fails, that metric is absent and
    the reading falls through to the metrics that did answer, because two scores still
    separate the stages and a fabricated zero would not.
    """
    relevance = triad.get("context_relevance")
    groundedness = triad.get("response_groundedness")
    answer_relevancy = triad.get("answer_relevancy")

    evidence: dict[str, Any] = {
        "context_relevance": relevance,
        "response_groundedness": groundedness,
        "answer_relevancy": answer_relevancy,
        "pass_mark": PASS_MARK,
    }

    if relevance is None and groundedness is None and answer_relevancy is None:
        return Diagnosis(
            "unknown",
            "No triad score was produced, so no stage can be named. Read the row's error "
            "or the worker log.",
            evidence,
        )

    if relevance is not None and relevance < PASS_MARK:
        stage, reason = _winner(
            retrieval_mrr=retrieval_mrr,
            rerank_mrr=rerank_mrr,
            rerank_enabled=rerank_enabled,
        )
        evidence["retrieval_mrr"] = retrieval_mrr
        evidence["rerank_mrr"] = rerank_mrr
        evidence["rerank_enabled"] = rerank_enabled
        return Diagnosis(stage, reason, evidence)

    if groundedness is not None and groundedness < PASS_MARK:
        return Diagnosis(
            "generation_grounding",
            f"The passages were relevant ({_fmt(relevance)}) but only {groundedness:.2f} of "
            "the answer is supported by them. The generator added statements its evidence "
            "does not carry.",
            evidence,
        )

    if answer_relevancy is not None and answer_relevancy < PASS_MARK:
        return Diagnosis(
            "generation_relevance",
            f"The answer is grounded ({_fmt(groundedness)}) but scores {answer_relevancy:.2f} "
            "against the question. It is supported and still does not answer what was asked.",
            evidence,
        )

    # A partial triad cannot certify a turn. Without this the reading above falls through to
    # "healthy" and prints "all three pass" over a row that scored one of them, which is how a
    # stale worker build reported a sound pipeline while two metrics were never computed.
    missing = [
        name
        for name, value in (
            ("context_relevance", relevance),
            ("response_groundedness", groundedness),
            ("answer_relevancy", answer_relevancy),
        )
        if value is None
    ]
    if missing:
        return Diagnosis(
            "unknown",
            f"The triad is incomplete: {', '.join(missing)} did not score, so no stage can be "
            "cleared. The judge call failed for those metrics; read the worker log.",
            evidence,
        )

    return Diagnosis(
        "healthy",
        "All three triad scores pass: the retriever found relevant passages, the answer "
        "stays inside them, and it addresses the question.",
        evidence,
    )


def _fmt(value: float | None) -> str:
    return "not scored" if value is None else f"{value:.2f}"


def stage_counts(diagnoses: list[Diagnosis]) -> dict[str, int]:
    """One count per stage, every stage present so a report never misses a column."""
    counts = {stage: 0 for stage in STAGES}
    for diagnosis in diagnoses:
        counts[diagnosis.stage] = counts.get(diagnosis.stage, 0) + 1
    return counts


def dominant_stage(counts: Mapping[str, int]) -> str | None:
    """The stage that owns the most failures, or None when nothing failed.

    `unknown` is excluded: it means the run produced no reading, which is a run
    problem rather than a pipeline problem, and naming it as the weak stage would
    hide the real one.
    """
    failures = {
        stage: n
        for stage, n in counts.items()
        if stage not in ("healthy", "unknown") and n
    }
    if not failures:
        return None
    return max(failures, key=lambda stage: failures[stage])
