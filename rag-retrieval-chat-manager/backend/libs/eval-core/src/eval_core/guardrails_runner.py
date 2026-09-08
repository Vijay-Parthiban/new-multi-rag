from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class GuardrailsEvalItem(BaseModel):
    item_id: str | None = None
    input_text: str
    expected_blocked: bool
    actual_blocked: bool
    expected_guard: str | None = None
    actual_guard: str | None = None
    passed: bool
    guard_results: dict[str, Any] = Field(default_factory=dict)


def evaluate_guardrails_item(
    input_text: str,
    expected_blocked: bool,
    expected_guard: str | None,
    actual_blocked: bool,
    actual_guard: str | None,
    guard_results: dict[str, Any] | None = None,
    item_id: str | None = None,
) -> GuardrailsEvalItem:
    passed = (expected_blocked == actual_blocked)
    if expected_blocked and expected_guard and actual_guard:
        passed = passed and (expected_guard == actual_guard)

    return GuardrailsEvalItem(
        item_id=item_id,
        input_text=input_text,
        expected_blocked=expected_blocked,
        actual_blocked=actual_blocked,
        expected_guard=expected_guard,
        actual_guard=actual_guard,
        passed=passed,
        guard_results=guard_results or {},
    )


def aggregate_guardrails_metrics(items: list[GuardrailsEvalItem]) -> dict[str, float]:
    if not items:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}

    total = len(items)
    correct = sum(1 for it in items if it.passed)

    tp = sum(1 for it in items if it.expected_blocked and it.actual_blocked)
    fp = sum(1 for it in items if not it.expected_blocked and it.actual_blocked)
    fn = sum(1 for it in items if it.expected_blocked and not it.actual_blocked)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "accuracy": round(correct / total, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }
