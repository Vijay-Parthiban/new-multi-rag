"""Unit tests for the guardrails evaluation runner.

These cover the scoring rules directly, without a live guardrails service. The runner is a
thin wrapper around the service, but the confusion matrix and the skip rule are real logic:
before this suite existed, the scoring call site had a parameter mismatch and every run
silently produced all-zero metrics.
"""

import pytest

from eval_core.guardrails_runner import (
    GuardrailsEvalItem,
    GuardrailsEvalOutcome,
    aggregate_guardrails_metrics,
    evaluate_guardrails_item,
)


def outcome(category, expected_blocked, actual_blocked, skipped=False, expected_guard=None, actual_guard=None):
    return GuardrailsEvalOutcome(
        category=category,
        skipped=skipped,
        expected_blocked=expected_blocked,
        actual_blocked=actual_blocked,
        correct_guard=(
            expected_guard == actual_guard if expected_guard and actual_guard else None
        ),
        expected_guard=expected_guard,
        actual_guard=actual_guard,
    )


def test_confusion_matrix_counts_each_quadrant():
    items = [
        outcome("a", True, True),    # true positive
        outcome("a", True, False),   # false negative
        outcome("a", False, True),   # false positive
        outcome("a", False, False),  # true negative
    ]
    m = aggregate_guardrails_metrics(items)

    assert m["true_positives"] == 1
    assert m["false_negatives"] == 1
    assert m["false_positives"] == 1
    assert m["true_negatives"] == 1
    # Two of the four rows are correct: the true positive and the true negative.
    assert m["accuracy"] == 0.5
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5


def test_skipped_rows_stay_out_of_the_scores():
    items = [
        outcome("a", True, True),
        outcome("a", False, False),
        outcome("a", True, False, skipped=True),  # must not count as a miss
    ]
    m = aggregate_guardrails_metrics(items)

    assert m["items_total"] == 3
    assert m["items_evaluated"] == 2
    assert m["items_skipped"] == 1
    assert m["accuracy"] == 1.0
    assert m["false_negatives"] == 0


def test_all_skipped_reports_zero_without_dividing_by_zero():
    m = aggregate_guardrails_metrics([outcome("a", True, True, skipped=True)])

    assert m["items_evaluated"] == 0
    assert m["accuracy"] == 0.0
    assert m["f1"] == 0.0


def test_empty_input_is_all_zeros():
    m = aggregate_guardrails_metrics([])

    assert m["items_total"] == 0
    assert m["accuracy"] == 0.0


def test_precision_is_one_when_nothing_was_blocked():
    # No false positives and no true positives. Reporting 0.0 here would be misleading.
    m = aggregate_guardrails_metrics([outcome("a", False, False)])

    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["accuracy"] == 1.0


def test_categories_are_grouped_and_rounded():
    items = [
        outcome("pii", True, True),
        outcome("pii", True, False),
        outcome("clean", False, False),
    ]
    m = aggregate_guardrails_metrics(items)

    assert m["categories"]["pii"]["item_count"] == 2
    assert m["categories"]["pii"]["correct"] == 1
    assert m["categories"]["pii"]["accuracy"] == 0.5
    assert m["categories"]["clean"]["accuracy"] == 1.0


def test_guard_match_rate_needs_a_comparable_pair():
    items = [
        GuardrailsEvalOutcome(expected_blocked=True, actual_blocked=True,
                              expected_guard="ban_list", actual_guard="ban_list",
                              correct_guard=True, correct_block=True),
        GuardrailsEvalOutcome(expected_blocked=True, actual_blocked=True,
                              expected_guard="ban_list", actual_guard="detect_pii",
                              correct_guard=False, correct_block=True),
        # No expected guard, so it cannot be compared and must not drag the rate down.
        GuardrailsEvalOutcome(expected_blocked=False, actual_blocked=False,
                              correct_block=True),
    ]
    m = aggregate_guardrails_metrics(items)

    assert m["guard_match_rate"] == 0.5


def test_failed_items_are_counted():
    failed = GuardrailsEvalOutcome(expected_blocked=True, correct_block=False,
                                   error_message="service unreachable")
    m = aggregate_guardrails_metrics([failed, outcome("a", False, False)])

    assert m["items_failed"] == 1
    assert m["accuracy"] == 0.5


def test_phase_excluded_by_mode_is_skipped_not_failed():
    item = GuardrailsEvalItem(text="anything", phase="output", expected_blocked=True)

    result = evaluate_guardrails_item(item, guards=["ban_list"], mode="input")

    assert result.skipped is True
    assert "output" in result.skip_reason
    assert result.actual_blocked is False


@pytest.mark.parametrize(
    ("mode", "phase", "expected_skip"),
    [("input", "input", False), ("input", "output", True),
     ("output", "input", True), ("output", "output", False),
     ("both", "input", False), ("both", "output", False)],
)
def test_mode_phase_matrix(mode, phase, expected_skip):
    from eval_core.guardrails_runner import _phase_allowed

    assert (not _phase_allowed(phase, mode)) is expected_skip
