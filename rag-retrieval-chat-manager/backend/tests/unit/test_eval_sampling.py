"""The offline evaluation's new entry points: the dataset import, and row sampling.

Both fail quietly when they are wrong. A bad column mapping imports rows nobody can answer, and
a bad sample evaluates a different set from the one the run claims to have measured. These
tests pin the mapping, the sampling rules and the config that carries a pipeline.
"""

from __future__ import annotations

import pytest

from eval_worker.tasks import _sample
from rag_api.routes.evaluate import EvalRunConfig, HF_DATASET, _hf_rows_to_items

HF_ROW = {
    "context": "This is the **x86_64-unknown-linux-musl** binary for `tokenizers`",
    "question": "What architecture is the `tokenizers-linux-x64-musl` binary designed for?",
    "answer": "x86_64-unknown-linux-musl",
    "source_doc": "huggingface/tokenizers/blob/main/bindings/node/npm/linux-x64-musl/README.md",
    "standalone_score": 5,
    "relevance_score": 3,
}


def test_a_hf_row_becomes_a_golden_item():
    items = _hf_rows_to_items([HF_ROW], HF_DATASET)

    assert len(items) == 1
    assert items[0].question.startswith("What architecture")
    assert items[0].ground_truth_answer == "x86_64-unknown-linux-musl"
    # source_doc names the file the answer came from, which is what retrieval is scored against.
    assert items[0].expected_sources == [{"name": HF_ROW["source_doc"]}]
    assert items[0].metadata["hf_dataset"] == HF_DATASET
    assert items[0].metadata["source_doc"] == HF_ROW["source_doc"]


def test_a_row_without_a_question_is_skipped_not_fatal():
    """The payload rejects a blank question, so one bad row must not fail the whole import."""
    rows = [HF_ROW, {**HF_ROW, "question": "   "}, {"question": None}]

    assert len(_hf_rows_to_items(rows, HF_DATASET)) == 1


def test_a_row_without_a_source_still_imports():
    items = _hf_rows_to_items([{**HF_ROW, "source_doc": ""}], HF_DATASET)

    assert items[0].expected_sources == []


@pytest.mark.parametrize("size", [None, 0, -1, 20, 999])
def test_a_size_that_does_not_narrow_returns_the_whole_set(size):
    """Asking for more rows than exist evaluates all of them rather than none."""
    items = [{"i": i} for i in range(20)]

    assert _sample(items, size, None) == items


def test_a_sample_returns_exactly_the_size_asked_for():
    items = [{"i": i} for i in range(65)]

    sampled = _sample(items, 5, None)

    assert len(sampled) == 5
    assert all(item in items for item in sampled)
    # No row is evaluated twice inside one run.
    assert len({id(item) for item in sampled}) == 5


def test_a_seeded_sample_is_reproducible():
    """A run records its seed, so the same sample has to come back from that seed."""
    items = [{"i": i} for i in range(65)]

    assert _sample(items, 5, 42) == _sample(items, 5, 42)


def test_different_seeds_draw_different_samples():
    items = [{"i": i} for i in range(65)]

    assert _sample(items, 5, 1) != _sample(items, 5, 2)


def test_no_narrowing_keeps_the_dataset_order():
    items = [{"i": i} for i in range(5)]

    assert [item["i"] for item in _sample(items, None, 7)] == [0, 1, 2, 3, 4]


def test_the_run_config_carries_the_pipeline_that_ran():
    config = EvalRunConfig(
        rag_strategy="hybrid",
        collection="kp_tcs_store_ef2631c1",
        opensearch_index="kp_tcs_store_ef2631c1",
        embedding_model="nvidia-embed-textonly",
        generation_model="groq-vision",
        sample_size=5,
    )

    dumped = config.model_dump()

    # These are what make the run measure the pipeline instead of the service default. Without
    # the strategy and the store names the evaluator reads the legacy scrape collection.
    assert dumped["rag_strategy"] == "hybrid"
    assert dumped["collection"] == "kp_tcs_store_ef2631c1"
    assert dumped["opensearch_index"] == "kp_tcs_store_ef2631c1"
    assert dumped["embedding_model"] == "nvidia-embed-textonly"
    assert dumped["generation_model"] == "groq-vision"
    assert dumped["sample_size"] == 5


def test_the_sample_size_is_bounded():
    with pytest.raises(ValueError):
        EvalRunConfig(sample_size=0)
    with pytest.raises(ValueError):
        EvalRunConfig(sample_size=501)


def test_a_run_with_no_sample_evaluates_everything():
    """A run that names no sample keeps the old behaviour: the whole dataset."""
    assert EvalRunConfig().sample_size is None
