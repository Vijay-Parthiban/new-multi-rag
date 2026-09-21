from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rag_shared.guardrails_client import check_blocked, run_guardrails_check


class GuardrailsEvalItem(BaseModel):
    """One labelled row from a guardrails golden dataset."""

    text: str
    phase: str = "input"
    expected_blocked: bool = False
    expected_guard: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuardrailsEvalOutcome(BaseModel):
    """What actually happened when the config ran over one dataset row."""

    skipped: bool = False
    skip_reason: str | None = None
    category: str | None = None
    expected_blocked: bool = False
    expected_guard: str | None = None
    actual_blocked: bool = False
    actual_guard: str | None = None
    correct_block: bool = False
    correct_guard: bool | None = None
    guard_results: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


def _phase_allowed(phase: str, mode: str) -> bool:
    """A config set to input only does not apply to output rows, and the reverse."""
    if mode == "both":
        return True
    return phase == mode


def evaluate_guardrails_item(
    item: GuardrailsEvalItem,
    *,
    guards: list[str],
    mode: str = "both",
    settings: dict[str, Any] | None = None,
    guardrails_url: str = "http://localhost:18000",
    timeout: float = 15.0,
) -> GuardrailsEvalOutcome:
    """Run one dataset row through the configured validators and score the result.

    The row is skipped, not failed, when the config mode excludes its phase.
    """
    if not _phase_allowed(item.phase, mode):
        return GuardrailsEvalOutcome(
            skipped=True,
            skip_reason=f"config mode is '{mode}' and this row is '{item.phase}'",
            category=item.category,
            expected_blocked=item.expected_blocked,
            expected_guard=item.expected_guard,
        )

    results = run_guardrails_check(
        item.text,
        guards,
        guardrails_url,
        timeout,
        settings=settings,
    )
    actual_blocked, actual_guard = check_blocked(results)

    outcome = GuardrailsEvalOutcome(
        category=item.category,
        expected_blocked=item.expected_blocked,
        expected_guard=item.expected_guard,
        actual_blocked=actual_blocked,
        actual_guard=actual_guard,
        correct_block=item.expected_blocked == actual_blocked,
        guard_results=results,
    )

    # The guard name only has to match when a block was expected and one happened.
    if item.expected_guard and actual_guard:
        outcome.correct_guard = item.expected_guard == actual_guard

    # A configuration or transport problem is reported per validator. Surface it so the row
    # is not mistaken for a clean pass.
    problems = [
        f"{name}: {res.get('error')}"
        for name, res in results.items()
        if res.get("error")
    ]
    if problems:
        outcome.error_message = "; ".join(problems)[:500]

    return outcome


def aggregate_guardrails_metrics(items: list[GuardrailsEvalOutcome]) -> dict[str, Any]:
    """Confusion matrix and derived scores over the evaluated rows.

    Skipped rows are counted separately and stay out of every score.
    """
    total = len(items)
    evaluated = [it for it in items if not it.skipped]
    skipped = total - len(evaluated)

    # Derive correctness from the expected and actual values. `correct_block` defaults to
    # False, so trusting a stored flag would quietly report zero for a caller that forgets
    # to set it.
    def is_correct(it: GuardrailsEvalOutcome) -> bool:
        return it.expected_blocked == it.actual_blocked

    metrics: dict[str, Any] = {
        "items_total": total,
        "items_evaluated": len(evaluated),
        "items_skipped": skipped,
        "items_failed": sum(1 for it in evaluated if it.error_message),
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "guard_match_rate": 0.0,
        "true_positives": 0,
        "true_negatives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "categories": {},
    }
    if not evaluated:
        return metrics

    tp = sum(1 for it in evaluated if it.expected_blocked and it.actual_blocked)
    tn = sum(1 for it in evaluated if not it.expected_blocked and not it.actual_blocked)
    fp = sum(1 for it in evaluated if not it.expected_blocked and it.actual_blocked)
    fn = sum(1 for it in evaluated if it.expected_blocked and not it.actual_blocked)

    correct = sum(1 for it in evaluated if is_correct(it))
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0

    guard_rows = [it for it in evaluated if it.correct_guard is not None]
    guard_match = (
        sum(1 for it in guard_rows if it.correct_guard) / len(guard_rows) if guard_rows else 0.0
    )

    categories: dict[str, dict[str, Any]] = {}
    for it in evaluated:
        name = it.category or "uncategorised"
        bucket = categories.setdefault(name, {"item_count": 0, "correct": 0, "accuracy": 0.0})
        bucket["item_count"] += 1
        bucket["correct"] += 1 if is_correct(it) else 0
    for bucket in categories.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["item_count"], 4)

    metrics.update(
        {
            "accuracy": round(correct / len(evaluated), 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "guard_match_rate": round(guard_match, 4),
            "true_positives": tp,
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
            "categories": categories,
        }
    )
    return metrics
