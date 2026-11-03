"""`dataset_items_to_jsonl` is the inverse of `parse_golden_dataset_jsonl`."""

from eval_core.dataset_schema import dataset_items_to_jsonl, parse_golden_dataset_jsonl


def test_single_turn_round_trip():
    item = {
        "question": "Who owns the lease?",
        "ground_truth_answer": "Acme",
        "expected_sources": [{"name": "a.pdf"}],
        "turns": None,
        "metadata": {"question_type": "single_hop", "source": "dataset_feedback"},
    }
    parsed = parse_golden_dataset_jsonl(dataset_items_to_jsonl([item]), name="t")
    assert parsed.kind == "single_turn"
    row = parsed.items[0]
    assert row.question == "Who owns the lease?"
    assert row.ground_truth_answer == "Acme"
    assert row.expected_sources == [{"name": "a.pdf"}]
    assert row.turns is None
    assert row.metadata["question_type"] == "single_hop"


def test_multi_turn_round_trip_and_unicode():
    turns = [{"role": "user", "content": "Wer ist Müller?"}, {"role": "user", "content": "Und sein Alter?"}]
    item = {
        "question": "Und sein Alter?",
        "ground_truth_answer": None,
        "expected_sources": [],
        "turns": turns,
        "metadata": {"expected_behavior": "refuse_or_abstain"},
    }
    data = dataset_items_to_jsonl([item, {**item, "question": "x2"}])
    assert "Müller" in data.decode("utf-8")
    parsed = parse_golden_dataset_jsonl(data, name="t")
    assert parsed.kind == "multi_turn"
    assert len(parsed.items) == 2
    assert [t.model_dump() for t in parsed.items[0].turns] == turns
    assert parsed.items[0].ground_truth_answer is None
    assert parsed.items[0].metadata["expected_behavior"] == "refuse_or_abstain"
