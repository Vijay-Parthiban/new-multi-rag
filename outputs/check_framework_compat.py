"""Re-run the framework-compatibility matrix from the brief.

Asserts what our loader accepts today. No service, no network, no deepeval install.

    backend/.venv/Scripts/python.exe outputs/check_framework_compat.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rag-retrieval-chat-manager/backend/libs/eval-core/src"))

from eval_core.dataset_schema import (  # noqa: E402
    parse_golden_dataset_csv,
    parse_golden_dataset_jsonl,
)

CASES = []


def case(name: str, expect: str = "loads"):
    def wrap(fn):
        CASES.append((name, expect, fn))
        return fn

    return wrap


@case("RAGAS single-turn JSONL")
def _ragas_single():
    row = {"user_input": "q", "reference": "a", "reference_contexts": ["c"],
           "synthesizer_name": "single_hop_specific_query_synthesizer"}
    ds = parse_golden_dataset_jsonl(json.dumps(row), name="x")
    assert ds.kind == "single_turn"
    assert ds.items[0].question == "q"
    assert ds.items[0].expected_sources == []          # no source in the framework's output
    assert "question_type" not in ds.items[0].metadata  # synthesizer_name dropped


@case("RAGAS multi-turn JSONL", expect="fails")
def _ragas_multi():
    row = {"user_input": [{"type": "human", "content": "q1"},
                          {"type": "ai", "content": "a1"},
                          {"type": "human", "content": "q2"}],
           "reference": "a2"}
    parse_golden_dataset_jsonl(json.dumps(row), name="x")


@case("RAGAS CSV")
def _ragas_csv():
    text = ("user_input,reference,reference_contexts\n"
            'What is X?,X is Y.,"[\'X is Y.\', \'X is Z.\']"\n')
    ds = parse_golden_dataset_csv(text, name="x")
    # Loads, but the gold context is the Python repr of the list, not the text.
    assert ds.items[0].metadata["reference_context"].startswith("['")


@case("DeepEval Golden JSONL")
def _deepeval_single():
    row = {"input": "q", "expected_output": "a", "context": ["c"],
           "additional_metadata": {"category": "single_hop"},
           "source_file": "Resume.pdf"}
    ds = parse_golden_dataset_jsonl(json.dumps(row), name="x")
    assert ds.items[0].question == "q"
    assert ds.items[0].expected_sources == []      # source_file dropped
    assert "category" not in ds.items[0].metadata  # additional_metadata dropped


@case("DeepEval ConversationalGolden with turns")
def _deepeval_multi():
    row = {"turns": [{"role": "user", "content": "q1"},
                     {"role": "assistant", "content": "a1"},
                     {"role": "user", "content": "q2"}],
           "expected_outcome": "a2"}
    ds = parse_golden_dataset_jsonl(json.dumps(row), name="x")
    assert ds.kind == "multi_turn"
    assert ds.items[0].question == "q2"


@case("DeepEval ConversationalGolden scenario-only", expect="fails")
def _deepeval_scenario():
    row = {"scenario": "user asks for help", "expected_outcome": "resolved"}
    parse_golden_dataset_jsonl(json.dumps(row), name="x")


@case("DeepEval CSV")
def _deepeval_csv():
    text = ("input,expected_output,context,metadata\n"
            "What is X?,X is Y.,X is Y.|X is Z.,\"{'category': 'single_hop'}\"\n")
    ds = parse_golden_dataset_csv(text, name="x")
    meta = ds.items[0].metadata
    # The metadata column arrives as a string key, not unpacked fields.
    assert "category" not in meta and "metadata" in meta


def main() -> int:
    passed = failed = 0
    for name, expect, fn in CASES:
        try:
            fn()
            ok = expect == "loads"
            detail = "loaded"
        except Exception as exc:  # noqa: BLE001 - the assertion is the expectation
            ok = expect == "fails"
            detail = f"{type(exc).__name__}: {str(exc).splitlines()[0][:70]}"
        print(("PASS " if ok else "FAIL ") + f"{name} (expected {expect}) — {detail}")
        passed += ok
        failed += not ok
    print(f"\n{passed}/{len(CASES)} as documented")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
