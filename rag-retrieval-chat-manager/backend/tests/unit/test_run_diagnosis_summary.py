"""A row that produced no reading must not be counted as a row that passed.

`unknown` means the row could not be scored at all: no retrieved contexts, no answer, the
judge unavailable, or a row that has not run yet. Counting it with the scored rows is how a
run that read nothing printed "All 65 scored rows pass" and hid a total retrieval failure.
"""

from rag_api.routes.evaluate import _diagnosis_summary, _run_diagnosis
from eval_core.attribution import STAGES


class _Item:
    """The three metric columns `list_run_item_metrics` returns."""

    def __init__(self, triad=None, retrieval=None, rerank=None):
        self.retrieval_metrics = retrieval or {}
        self.rerank_metrics = rerank or {}
        self.generation_metrics = triad or {}


def _counts(**over):
    base = {stage: 0 for stage in STAGES}
    base.update(over)
    return base


def test_unscored_rows_are_not_called_passing():
    """Every row unscored: the reading must say so, not claim a clean run."""
    summary = _diagnosis_summary(_counts(unknown=65), None)

    assert "All" not in summary
    assert "pass" not in summary.lower()
    assert "65" in summary
    assert "unscored" in summary.lower()


def test_unscored_rows_are_named_in_the_summary():
    summary = _diagnosis_summary(_counts(healthy=10, unknown=2), None)

    assert "10 scored rows pass" in summary
    assert "2 row(s) produced no score" in summary


def test_a_run_with_no_rows_yet_says_so():
    summary = _diagnosis_summary(_counts(), None)

    assert "No row has been scored yet" in summary


def test_the_scored_count_excludes_unscored_rows():
    diagnostics = _run_diagnosis(
        [
            _Item(triad={"context_relevance": 0.9, "response_groundedness": 0.9, "answer_relevancy": 0.9}),
            _Item(),  # no metrics at all
        ],
        {"rerank_enabled": True},
    )

    assert diagnostics["scored_items"] == 1
    assert diagnostics["unscored_items"] == 1
    assert diagnostics["stage_counts"]["unknown"] == 1
    assert "1 scored rows pass" in diagnostics["summary"]


def test_reranking_off_moves_a_rerank_verdict_to_retrieval():
    """The same row is read differently when the run had no reranker."""
    row = _Item(
        triad={"context_relevance": 0.2, "response_groundedness": 0.9, "answer_relevancy": 0.9},
        rerank={"mrr_before_at_k": 0.9, "mrr_after": 0.1},
    )

    with_rerank = _run_diagnosis([row], {"rerank_enabled": True})
    without_rerank = _run_diagnosis([row], {"rerank_enabled": False})

    assert with_rerank["dominant_stage"] == "rerank"
    assert without_rerank["dominant_stage"] == "retrieval"


def test_the_diagnosis_uses_the_equal_depth_mrr():
    """`mrr_before_at_k` is the retrieved ranking cut to the reranker's depth. With it, a
    retriever that never ranked the evidence inside the top-k does not blame the reranker."""
    row = _Item(
        triad={"context_relevance": 0.2, "response_groundedness": 0.9, "answer_relevancy": 0.9},
        retrieval={"mrr": 0.5},  # over all 20 retrieved
        rerank={"mrr_before_at_k": 0.0, "mrr_after": 0.0},  # over the top 5 only
    )

    result = _run_diagnosis([row], {"rerank_enabled": True})

    assert result["dominant_stage"] == "retrieval"
