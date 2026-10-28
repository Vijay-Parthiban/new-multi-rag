"""The loader accepts the column names DeepEval and RAGAS write.

The point of these cases is that a dataset either framework generates loads with no
renaming step, and that a multi-turn dataset survives the trip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_core.dataset_schema import (
    parse_golden_dataset_csv,
    parse_golden_dataset_jsonl,
    parse_golden_dataset_payload,
)

RESUMES = Path(__file__).resolve().parents[4] / "resumes"
SINGLE_TURN_CSV = RESUMES / "resume_single_turn_golden.csv"

RAGAS_CSV = (
    "user_input,reference,reference_contexts\n"
    "Who approved the policy?,The Board of Directors.,The board approved it on 1 May.\n"
    "What is the retention period?,Seven years.,Records are kept for seven years.\n"
)

DEEPEVAL_CSV = (
    "input,expected_output,context\n"
    "Who approved the policy?,The Board of Directors.,The board approved it on 1 May.\n"
    "What is the retention period?,Seven years.,Records are kept for seven years.\n"
)

CANONICAL_CSV = (
    "id,question,reference_context,ground_truth_answer,source_doc_id,question_type\n"
    "Q001,Who approved the policy?,The board approved it.,The Board of Directors.,CSR_p5,single_hop\n"
    "Q002,What is the retention period?,Records are kept.,Seven years.,CSR_p6,single_hop\n"
)

TURNS = [
    {"role": "user", "content": "Which candidate has the most experience?"},
    {"role": "user", "content": "What was their most recent role?"},
]


def _turns_cell(turns: list[dict[str, str]]) -> str:
    return json.dumps(turns)


def _csv_cell(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


MULTI_TURN_CSV = f"id,question_type,source_doc_id,turns\nC001,follow_up,Resume-1.pdf,{_csv_cell(_turns_cell(TURNS))}\n"


def test_reads_ragas_column_names():
    payload = parse_golden_dataset_csv(RAGAS_CSV, name="Ragas")
    assert payload.items[0].question == "Who approved the policy?"
    assert payload.items[0].ground_truth_answer == "The Board of Directors."
    assert payload.items[0].metadata["reference_context"] == "The board approved it on 1 May."
    assert payload.kind == "single_turn"


def test_reads_deepeval_column_names():
    payload = parse_golden_dataset_csv(DEEPEVAL_CSV, name="Deepeval")
    assert payload.items[1].question == "What is the retention period?"
    assert payload.items[1].ground_truth_answer == "Seven years."
    assert payload.items[1].metadata["reference_context"] == "Records are kept for seven years."


def test_canonical_names_still_load_and_extra_columns_stay_in_metadata():
    payload = parse_golden_dataset_csv(CANONICAL_CSV, name="Canonical")
    item = payload.items[0]
    assert item.question == "Who approved the policy?"
    assert item.ground_truth_answer == "The Board of Directors."
    assert item.expected_sources == [{"name": "CSR_p5"}]
    assert item.metadata["question_type"] == "single_hop"
    assert item.turns is None


def test_multi_turn_row_derives_the_question_and_is_multi_turn():
    payload = parse_golden_dataset_csv(MULTI_TURN_CSV, name="Convo")
    assert payload.kind == "multi_turn"
    item = payload.items[0]
    assert [turn.role for turn in item.turns or []] == ["user", "user"]
    assert item.question == "What was their most recent role?"


def test_mixed_kinds_are_rejected():
    mixed = (
        "id,question,turns\n"
        "Q001,Who approved the policy?,\n"
        f"C001,,{_csv_cell(_turns_cell(TURNS))}\n"
    )
    with pytest.raises(ValueError, match="cannot mix single-turn and multi-turn"):
        parse_golden_dataset_csv(mixed, name="Mixed")


def test_turns_without_a_user_turn_are_rejected():
    empty = 'id,question,turns\nC001,Ask something,"[]"\n'
    with pytest.raises(ValueError, match="at least one user turn"):
        parse_golden_dataset_csv(empty, name="Convo")

    assistant_only = (
        "id,question,turns\nC002,Ask something,"
        + _csv_cell(_turns_cell([{"role": "assistant", "content": "Sure."}]))
        + "\n"
    )
    with pytest.raises(ValueError, match="at least one user turn"):
        parse_golden_dataset_csv(assistant_only, name="Convo")


def test_jsonl_is_one_item_per_line():
    text = (
        json.dumps(
            {
                "user_input": "Who approved the policy?",
                "reference": "The Board of Directors.",
                "reference_contexts": ["The board approved it."],
            }
        )
        + "\n\n"
        + json.dumps(
            {
                "user_input": "What is the retention period?",
                "reference": "Seven years.",
                "reference_contexts": ["Records are kept for seven years."],
            }
        )
    )
    payload = parse_golden_dataset_jsonl(text, name="Jsonl")
    assert len(payload.items) == 2
    assert payload.items[1].question == "What is the retention period?"
    assert payload.items[1].ground_truth_answer == "Seven years."


def test_jsonl_multi_turn_line_takes_its_turns_from_user_input():
    """RAGAS writes a conversation into `user_input` as a list of messages."""
    text = json.dumps(
        {
            "user_input": [
                {"role": "user", "content": "Which company does Rohan Sinha work for now?"},
                {"role": "user", "content": "What is his title there?"},
            ],
            "reference": "Senior Software Engineer at Google.",
        }
    )
    payload = parse_golden_dataset_jsonl(text, name="Convo")
    assert payload.kind == "multi_turn"
    assert payload.items[0].question == "What is his title there?"
    assert len(payload.items[0].turns or []) == 2


def test_the_json_body_route_accepts_both_frameworks_names():
    """`POST /evaluate/datasets` goes through the same normalization a file upload does."""
    payload = parse_golden_dataset_payload(
        {
            "name": "Body",
            "items": [
                {"user_input": "Who approved?", "reference": "The Board.", "reference_contexts": ["c"]},
            ],
        }
    )
    assert payload.items[0].question == "Who approved?"
    assert payload.items[0].ground_truth_answer == "The Board."

    convo = parse_golden_dataset_payload(
        {
            "name": "Body",
            "items": [
                {
                    "user_input": [
                        {"role": "user", "content": "who?"},
                        {"role": "user", "content": "their title?"},
                    ],
                    "reference": "Engineer.",
                }
            ],
        }
    )
    assert convo.kind == "multi_turn"
    assert convo.items[0].question == "their title?"


def test_normalizing_a_normalized_payload_changes_nothing():
    raw = {
        "name": "N",
        "items": [
            {
                "user_input": [
                    {"role": "user", "content": "who?"},
                    {"role": "user", "content": "their title?"},
                ],
                "reference": "Engineer.",
            }
        ],
    }
    once = parse_golden_dataset_payload(raw)
    twice = parse_golden_dataset_payload(
        {"name": once.name, "items": [item.model_dump() for item in once.items]}
    )
    assert twice.items[0].question == once.items[0].question
    assert twice.items[0].turns == once.items[0].turns
    assert twice.kind == "multi_turn"


def test_the_single_turn_dataset_is_valid_for_ragas():
    """The compatibility claim, proven rather than asserted.

    `from_list`, not `from_csv`: a CSV cell is text, so a list-valued field such as
    `reference_contexts` comes back as a string and pydantic rejects it.
    """
    from ragas import EvaluationDataset

    payload = parse_golden_dataset_csv(SINGLE_TURN_CSV.read_text(encoding="utf-8"), name="Resumes")
    assert len(payload.items) == 10

    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": item.question,
                "reference": item.ground_truth_answer or "",
                "reference_contexts": [item.metadata.get("reference_context", "")],
            }
            for item in payload.items
        ]
    )
    assert len(dataset.samples) == 10


def test_the_multi_turn_dataset_is_ten_conversations():
    payload = parse_golden_dataset_csv(
        (RESUMES / "resume_multi_turn_golden.csv").read_text(encoding="utf-8"), name="Resumes MT"
    )
    assert payload.kind == "multi_turn"
    assert len(payload.items) == 10
    for item in payload.items:
        assert item.turns and item.turns[-1].content == item.question
        assert any(turn.role == "user" for turn in item.turns)
