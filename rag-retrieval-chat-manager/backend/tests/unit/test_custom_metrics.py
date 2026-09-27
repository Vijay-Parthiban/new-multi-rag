"""The golden-dataset CSV parser and the two metrics RAGAS does not provide."""

from __future__ import annotations

import pytest

from eval_core.custom_metrics import (
    ABSTAIN_BEHAVIOR,
    behavior_match,
    compute_custom_metrics,
    keypoint_coverage,
)
from eval_core.dataset_schema import parse_golden_dataset_csv

REFUSAL = "The provided policy document does not address this; I do not have information."

CSV = """id,question_type,question,reference_context,ground_truth_answer,source_doc_id,keypoints_covered,expected_behavior,difficulty
Q001,single_hop_factual,Who approved the policy?,"Policy v10.0, approved by the Board.",The Board of Directors.,WB_p1,approver=Board of Directors,answer_correctly,easy
Q002,multi_hop_reasoning,Version and date?,"Version 10.0, 09 April 2026.","Version 10.0, 09 April 2026.",CSR_p5;CSR_p6,version=10.0;date=09 April 2026,answer_correctly,hard
Q003,unanswerable,What is the fine?,NONE - the document holds no fine.,The document does not specify a fine.,N/A,refusal_expected,refuse_or_abstain,medium
"""


def test_parses_every_row():
    payload = parse_golden_dataset_csv(CSV, name="Sample")
    assert payload.name == "Sample"
    assert [item.question for item in payload.items] == [
        "Who approved the policy?",
        "Version and date?",
        "What is the fine?",
    ]


def test_maps_the_answer_and_drops_the_none_reference():
    payload = parse_golden_dataset_csv(CSV, name="Sample")
    assert payload.items[0].ground_truth_answer == "The Board of Directors."
    # The unanswerable row marks its reference with `NONE -`. Storing that sentence would
    # make context precision measure against the words "the document holds no fine".
    assert "reference_context" not in payload.items[2].metadata
    assert payload.items[0].metadata["reference_context"].startswith("Policy v10.0")


def test_splits_multiple_sources():
    payload = parse_golden_dataset_csv(CSV, name="Sample")
    assert payload.items[1].expected_sources == [{"name": "CSR_p5"}, {"name": "CSR_p6"}]
    # `N/A` is a missing source, not a source named "N/A".
    assert payload.items[2].expected_sources == []


def test_keeps_the_extra_columns_in_metadata():
    payload = parse_golden_dataset_csv(CSV, name="Sample")
    meta = payload.items[0].metadata
    assert meta["id"] == "Q001"
    assert meta["question_type"] == "single_hop_factual"
    assert meta["expected_behavior"] == "answer_correctly"
    assert meta["keypoints_covered"] == "approver=Board of Directors"


def test_requires_a_question_column():
    with pytest.raises(ValueError, match="question"):
        parse_golden_dataset_csv("id,foo\n1,bar\n", name="Sample")


def test_requires_a_name():
    with pytest.raises(ValueError, match="name"):
        parse_golden_dataset_csv(CSV)


def test_tolerates_header_case_and_spacing():
    payload = parse_golden_dataset_csv(" Question , Ground_Truth_Answer \nQ?,A.\n", name="S")
    assert payload.items[0].question == "Q?"
    assert payload.items[0].ground_truth_answer == "A."


def test_behavior_match_rewards_the_expected_behavior():
    assert behavior_match(ABSTAIN_BEHAVIOR, REFUSAL) == 1.0
    assert behavior_match(ABSTAIN_BEHAVIOR, "The fine is 50000 rupees.") == 0.0
    assert behavior_match("answer_correctly", "The Board of Directors.") == 1.0
    assert behavior_match("answer_correctly", REFUSAL) == 0.0


def test_behavior_match_is_one_metric_for_every_row():
    """One column must mean one thing, or its mean has no interpretation."""
    # The same answer scores 0.0 on a row that wanted an answer and 0.0 on a row that
    # wanted a refusal only when it is wrong for that row. Both are `behavior_match`.
    assert behavior_match("answer_correctly", REFUSAL) == behavior_match(ABSTAIN_BEHAVIOR, "The fine is 50000.")


def test_keypoint_coverage_counts_present_values():
    assert keypoint_coverage("version=10.0", "Version 10.0 was released.") == 1.0
    assert keypoint_coverage("version=10.0;date=09 April 2026", "Version 10.0 was released.") == 0.5
    assert keypoint_coverage("version=10.0", "Nothing relevant.") == 0.0


def test_keypoint_coverage_needs_every_part_of_a_comma_value():
    assert keypoint_coverage("languages=English,Hindi", "English, Hindi and local.") == 1.0
    assert keypoint_coverage("languages=English,Hindi", "Only English is allowed.") == 0.0


def test_keypoint_coverage_is_none_when_the_row_lists_only_tags():
    """`mode1;mode2` names no phrase. Scoring it 0.0 would drag the mean down."""
    assert keypoint_coverage("mode1;mode2", "NGOs and the TCS Foundation.") is None
    assert keypoint_coverage("informed;cooperate", "The Subject cooperates.") is None
    assert keypoint_coverage(None, "anything") is None


def test_absent_metrics_are_left_out_not_zeroed():
    metadata = {"expected_behavior": "refuse_or_abstain", "keypoints_covered": "refusal_expected"}
    assert compute_custom_metrics(metadata, REFUSAL) == {"behavior_match": 1.0}

    tags_only = {"expected_behavior": "answer_correctly", "keypoints_covered": "mode1;mode2"}
    assert compute_custom_metrics(tags_only, "An answer.") == {"behavior_match": 1.0}


def test_no_metadata_gives_no_metrics():
    assert compute_custom_metrics(None, "An answer.") == {}
    assert compute_custom_metrics({}, "An answer.") == {}
