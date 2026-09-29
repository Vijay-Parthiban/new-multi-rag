"""The triad names the stage that failed, and the reading has to be exact.

A single overall score says a pipeline is bad. It does not say whether the retriever handed
over the wrong passages, the reranker buried the right one, or the generator ignored what
it was given, and each of those needs a different fix. These tests pin the mapping from
three scores to one stage, including the cases where a judge call failed and only some of
the three came back.
"""

from eval_core.attribution import (
    PASS_MARK,
    RERANK_LOSS_MARGIN,
    STAGES,
    diagnose,
    dominant_stage,
    stage_counts,
)


def _triad(context_relevance=None, response_groundedness=None, answer_relevancy=None):
    return {
        "context_relevance": context_relevance,
        "response_groundedness": response_groundedness,
        "answer_relevancy": answer_relevancy,
    }


def test_all_three_passing_is_sound():
    result = diagnose(_triad(0.9, 0.9, 0.9))

    assert result.stage == "healthy"


def test_a_score_exactly_on_the_pass_mark_passes():
    """The mark is a floor, not a threshold to beat."""
    result = diagnose(_triad(PASS_MARK, PASS_MARK, PASS_MARK))

    assert result.stage == "healthy"


def test_irrelevant_context_blames_retrieval():
    result = diagnose(_triad(0.2, 0.9, 0.9))

    assert result.stage == "retrieval"


def test_a_reranker_that_lost_the_evidence_takes_the_blame():
    """The retriever ranked it and the reranked top-k did not."""
    result = diagnose(_triad(0.3, 0.9, 0.9), retrieval_mrr=0.9, rerank_mrr=0.1)

    assert result.stage == "rerank"
    assert "reranker" in result.reason.lower() or "rerank" in result.reason.lower()


def test_the_reranker_keeps_the_blame_only_past_the_margin():
    """A rounding-sized dip in MRR is not a reranker fault."""
    same = diagnose(_triad(0.3, 0.9, 0.9), retrieval_mrr=0.5, rerank_mrr=0.5)
    tiny = diagnose(
        _triad(0.3, 0.9, 0.9),
        retrieval_mrr=0.5,
        rerank_mrr=0.5 - RERANK_LOSS_MARGIN / 2,
    )

    assert same.stage == "retrieval"
    assert tiny.stage == "retrieval"


def test_reranking_that_did_not_run_is_never_blamed():
    """The reranker cannot own a miss when it was switched off. The truncation to top_k
    would otherwise read as a reranker fault for a stage that never executed."""
    result = diagnose(_triad(0.3, 0.9, 0.9), retrieval_mrr=0.9, rerank_mrr=0.1, rerank_enabled=False)

    assert result.stage == "retrieval"
    assert "off" in result.reason.lower()


def test_the_rerank_gate_defaults_to_on():
    """A caller that does not track the setting keeps the rerank verdict."""
    result = diagnose(_triad(0.3, 0.9, 0.9), retrieval_mrr=0.9, rerank_mrr=0.1)

    assert result.stage == "rerank"


def test_without_mrr_numbers_the_retriever_owns_the_miss():
    """The retriever is the stage the context relevance score actually measured."""
    result = diagnose(_triad(0.2, 0.9, 0.9))

    assert result.stage == "retrieval"


def test_relevant_context_with_an_invented_answer_blames_generation():
    result = diagnose(_triad(0.9, 0.2, 0.9))

    assert result.stage == "generation_grounding"


def test_a_grounded_answer_to_the_wrong_question_blames_generation():
    result = diagnose(_triad(0.9, 0.9, 0.1))

    assert result.stage == "generation_relevance"


def test_retrieval_is_reported_before_grounding():
    """Both low: fix the retrieved passages first, because grounding cannot be judged
    against evidence that is not relevant."""
    result = diagnose(_triad(0.1, 0.1, 0.1))

    assert result.stage == "retrieval"


def test_a_failed_judge_call_is_absent_not_zero():
    """One missing score must not fabricate a failure for the stage it covers.

    It must not certify the turn either. A row that scored one of three is incomplete, and
    saying "healthy" over it is how a stale worker reported a sound pipeline while two
    metrics were never computed.
    """
    result = diagnose(_triad(context_relevance=None, response_groundedness=0.9, answer_relevancy=0.9))

    assert result.stage == "unknown"
    assert "context_relevance" in result.reason


def test_a_partial_triad_names_every_metric_that_did_not_score():
    result = diagnose(_triad(context_relevance=None, response_groundedness=None, answer_relevancy=0.9))

    assert result.stage == "unknown"
    assert "context_relevance" in result.reason
    assert "response_groundedness" in result.reason


def test_a_present_failure_still_wins_over_a_missing_score():
    """A real fault outranks an incomplete reading: name the stage, do not just say unknown."""
    result = diagnose(_triad(0.1, None, 0.9))

    assert result.stage == "retrieval"


def test_healthy_requires_all_three_scores():
    result = diagnose(_triad(0.9, 0.9, 0.9))

    assert result.stage == "healthy"


def test_a_failed_grounding_call_still_reads_the_other_two():
    result = diagnose(_triad(0.9, None, 0.2))

    assert result.stage == "generation_relevance"


def test_no_scores_at_all_is_unknown():
    """Not a pipeline fault: the run produced no reading, so no stage can be named."""
    result = diagnose(_triad())

    assert result.stage == "unknown"
    assert "no triad score" in result.reason.lower()


def test_every_reading_carries_its_numbers():
    result = diagnose(_triad(0.2, 0.8, 0.9), retrieval_mrr=0.7, rerank_mrr=0.7)
    evidence = result.evidence

    assert evidence["context_relevance"] == 0.2
    assert evidence["pass_mark"] == PASS_MARK
    assert evidence["retrieval_mrr"] == 0.7


def test_stage_counts_always_carries_every_stage():
    """A report must not lose a column because no row landed in it."""
    counts = stage_counts([diagnose(_triad(0.9, 0.9, 0.9))])

    assert set(counts) == set(STAGES)
    assert counts["healthy"] == 1
    assert counts["retrieval"] == 0


def test_the_dominant_stage_is_the_one_with_the_most_failures():
    counts = stage_counts(
        [
            diagnose(_triad(0.1, 0.9, 0.9)),
            diagnose(_triad(0.1, 0.9, 0.9)),
            diagnose(_triad(0.9, 0.1, 0.9)),
            diagnose(_triad(0.9, 0.9, 0.9)),
        ]
    )

    assert dominant_stage(counts) == "retrieval"


def test_an_all_healthy_run_has_no_dominant_stage():
    counts = stage_counts([diagnose(_triad(0.9, 0.9, 0.9))])

    assert dominant_stage(counts) is None


def test_unknown_is_never_named_the_weak_stage():
    """Unknown means the run produced no reading. Naming it would hide the real fault."""
    counts = stage_counts([diagnose(_triad()), diagnose(_triad()), diagnose(_triad(0.1, 0.9, 0.9))])

    assert dominant_stage(counts) == "retrieval"
