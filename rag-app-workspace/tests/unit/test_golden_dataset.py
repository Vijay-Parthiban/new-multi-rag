from __future__ import annotations

import json
from pathlib import Path

from eval_core.dataset_schema import parse_golden_dataset_json

DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "golden" / "golden-dataset.json"


def test_golden_dataset_file_structure():
    payload = parse_golden_dataset_json(DATASET_PATH.read_text(encoding="utf-8"))
    assert payload.name == "scrape-corpus-golden"
    assert len(payload.items) >= 20

    for item in payload.items:
        assert item.question.strip()
        assert item.ground_truth_answer
        assert isinstance(item.expected_sources, list)
