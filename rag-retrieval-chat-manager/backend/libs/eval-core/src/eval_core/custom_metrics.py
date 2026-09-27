"""Metrics a golden dataset carries that RAGAS does not score.

RAGAS covers retrieval and grounding. Two things a hand-written dataset asks about have no
RAGAS metric: whether the system did what the row said it should, and whether an answer
covered every keypoint the author listed. Both are plain string checks, so they run
in-process with no judge model and no cost.
"""

from __future__ import annotations

import re
from typing import Any

# The `expected_behavior` value that says the corpus holds no answer and the system must
# say so rather than invent one.
ABSTAIN_BEHAVIOR = "refuse_or_abstain"

# Phrases that mark a refusal. Deliberately broad: an abstention that misses every marker
# scores zero, so the list errs toward recognising the honest ways to say "I do not know".
_ABSTENTION_MARKERS = (
    "does not address",
    "does not contain",
    "does not include",
    "does not provide",
    "does not specify",
    "does not state",
    "do not have information",
    "don't have information",
    "no information",
    "no provision",
    "no such",
    "not available",
    "not mentioned",
    "not specified",
    "not stated",
    "not addressed",
    "cannot be determined",
    "cannot determine",
    "unable to find",
)

# A keypoint list looks like `version=10.0;date=09 April 2026` or `channel1=CEC email`.
# The label side is a tag for the author, so only the value side is matched.
_KEYPOINT_SPLIT = re.compile(r"[;\n]")


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def answered_abstention(answer: str) -> bool:
    """True when the answer declines to answer.

    ponytail: a marker match, not a judgement of whether a *claim* was invented. It reads
    the wording, so a fluent wrong answer that happens to contain "not specified" counts
    as an abstention. Replace with a judge call if that shows up in a real run.
    """
    text = _normalize(answer)
    if not text:
        return True
    return any(marker in text for marker in _ABSTENTION_MARKERS)


def behavior_match(expected_behavior: str | None, answer: str) -> float:
    """1.0 when the answer behaves the way the dataset row says it should.

    One metric for every row, so the mean means one thing. A `refuse_or_abstain` row wants
    an abstention; every other row wants a real answer. Keeping this as a single column
    matters: an earlier version scored "did abstain" on some rows and "did not abstain" on
    others, which averages to a number with no interpretation.
    """
    expected = _normalize(expected_behavior)
    if not expected:
        return 0.0
    did_abstain = answered_abstention(answer)
    if expected == ABSTAIN_BEHAVIOR:
        return 1.0 if did_abstain else 0.0
    return 0.0 if did_abstain else 1.0


def keypoint_coverage(keypoints: str | None, answer: str) -> float | None:
    """Fraction of the listed keypoints present in the answer, or None when the row's
    keypoints carry no matchable text.

    None rather than 0.0 matters: some rows list bare tags (`mode1;mode2`, `informed;
    cooperate`) that name no phrase an answer could contain. Scoring those 0.0 would pull
    the mean down for a row that was never measurable.

    A keypoint is `label=value` or a multi-word phrase. A comma-separated value counts as
    covered only when every part appears, so `languages=English,Hindi` needs both.
    """
    text = _normalize(answer)
    if not text or not keypoints:
        return None

    entries: list[str] = []
    for raw in _KEYPOINT_SPLIT.split(str(keypoints)):
        entry = raw.strip()
        if not entry:
            continue
        _, sep, value = entry.partition("=")
        if sep and value.strip():
            entries.append(value.strip())
        elif " " in entry:
            entries.append(entry)

    if not entries:
        return None

    covered = 0
    for entry in entries:
        parts = [_normalize(p) for p in entry.split(",") if p.strip()]
        if parts and all(part in text for part in parts):
            covered += 1
    return covered / len(entries)


def compute_custom_metrics(metadata: dict[str, Any] | None, answer: str) -> dict[str, float]:
    """Both metrics, each only where the dataset gives something to measure.

    A key is absent when the dataset row does not carry the input. The aggregate averages
    over present values, so a missing key never drags a mean toward zero.
    """
    meta = metadata or {}
    out: dict[str, float] = {}

    behavior = _normalize(meta.get("expected_behavior"))
    if behavior:
        out["behavior_match"] = behavior_match(behavior, answer)

    keypoints = meta.get("keypoints_covered")
    if keypoints and _normalize(keypoints) != "refusal_expected":
        coverage = keypoint_coverage(str(keypoints), answer)
        # None means the row listed tags rather than phrases. Leaving the key out keeps the
        # aggregate mean over the rows that were actually measurable.
        if coverage is not None:
            out["keypoint_coverage"] = coverage

    return out
