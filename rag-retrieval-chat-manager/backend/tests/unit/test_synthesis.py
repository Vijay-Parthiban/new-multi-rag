from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from eval_core.synthesis import (
    ContextGroup,
    LiteLlmModel,
    build_contexts,
    build_synthesizer,
    _multi_row,
    _split_turns,
)


class _ReplyModel:
    """A LiteLlmModel stand-in: `generate` returns the queued replies in order."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)

    def get_model_name(self) -> str:
        return "test-model"


def test_build_contexts_groups_by_file_and_skips_parent_and_blank_text():
    chunks = [
        {"file_key": "b.pdf", "page_index": 0, "chunk_index": 0, "text": "b0"},
        {"file_key": "a.pdf", "page_index": 1, "chunk_index": 1, "text": "a1b"},
        {"file_key": "a.pdf", "page_index": 1, "chunk_index": 0, "text": "a1a"},
        {"file_key": "a.pdf", "page_index": 0, "chunk_index": 0, "text": ""},
        {"file_key": "a.pdf", "page_index": 0, "chunk_index": 1, "text": "a0b"},
        {"file_key": "a.pdf", "page_index": 0, "chunk_index": 2, "text": "parent", "record_type": "parent"},
        {"file_key": "a.pdf", "page_index": 0, "chunk_index": 0, "text": "a0a"},
    ]

    groups = build_contexts(chunks, chunks_per_context=2)

    assert [(g.file_key, g.texts) for g in groups] == [
        ("a.pdf", ["a0a", "a0b"]),
        ("a.pdf", ["a1a", "a1b"]),
        ("b.pdf", ["b0"]),
    ]


def test_build_contexts_dedupes_a_repeated_chunk():
    chunk = {"file_key": "a.pdf", "page_index": 0, "chunk_index": 0, "text": "a0"}
    groups = build_contexts([chunk, dict(chunk)], chunks_per_context=4)
    assert groups == [ContextGroup(file_key="a.pdf", texts=["a0"])]


def test_split_turns_returns_the_turns_in_order():
    model = _ReplyModel(
        ['```json\n{"turns": [{"question": "Q1?", "answer": "A1."},'
         ' {"question": "Q2?", "answer": "A2."}]}\n```']
    )

    turns = _split_turns(model, scenario="S", expected_outcome="E", context=["ctx"], turns=2)

    assert turns == [{"question": "Q1?", "answer": "A1."}, {"question": "Q2?", "answer": "A2."}]
    assert len(model.prompts) == 1
    assert "Write exactly 2 user turns" in model.prompts[0]


def test_split_turns_retries_once_after_an_invalid_reply():
    model = _ReplyModel(
        [
            '{"turns": []}',
            '{"turns": [{"question": "Q1?", "answer": "A1."}]}',
        ]
    )

    turns = _split_turns(model, scenario="S", expected_outcome="E", context=["ctx"], turns=1)

    assert turns == [{"question": "Q1?", "answer": "A1."}]
    assert len(model.prompts) == 2
    assert "Your previous reply was invalid" in model.prompts[1]


def test_split_turns_gives_up_after_two_invalid_replies():
    model = _ReplyModel(["not json", '{"turns": [{"question": "", "answer": "A1."}]}'])
    assert _split_turns(model, scenario="S", expected_outcome="E", context=["ctx"], turns=1) is None
    assert len(model.prompts) == 2


def test_multi_row_uses_the_last_turn_as_its_question():
    golden = SimpleNamespace(
        scenario="Compare two candidates.",
        expected_outcome="A table.",
        additional_metadata={"evolutions": ["multicontext"], "synthetic_input_quality": 0.9},
    )
    group = ContextGroup(file_key="a.pdf", texts=["ctx one"])
    qa = [
        {"question": "Q1?", "answer": "A1."},
        {"question": "Q2?", "answer": "A2."},
    ]

    row = _multi_row(golden, group, qa, model="m", profile_id="p", version_id="v")

    assert row["question"] == "Q2?"
    assert row["ground_truth_answer"] == "A2."
    assert row["turns"] == [
        {"role": "user", "content": "Q1?"},
        {"role": "user", "content": "Q2?"},
    ]
    assert row["metadata"]["expected_turns"] == [{"content": "A1."}, {"content": "A2."}]
    assert row["metadata"]["scenario"] == "Compare two candidates."
    assert row["metadata"]["expected_outcome"] == "A table."
    assert row["metadata"]["synthetic_version_id"] == "v"
    assert row["expected_sources"] == ["a.pdf"]


def test_build_synthesizer_disables_filtration_and_normalises_evolution_weights():
    config = {
        "evolutions": ["multicontext", "concretizing", "constrained", "comparative"],
        "num_evolutions": 1,
        "filtration": {"enabled": False, "threshold": 0.9, "max_retries": 9},
        "styling": {"task": "answer questions", "scenario": None},
        "conversational_styling": {},
    }

    synth = build_synthesizer(config, LiteLlmModel("gpt-test", "http://localhost:4000", "sk-test"))

    assert synth.filtration_config.synthetic_input_quality_threshold == 0.0
    assert synth.filtration_config.max_quality_retries == 1
    weights = synth.evolution_config.evolutions
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert all(weight == 0.25 for weight in weights.values())
    assert synth.styling_config is not None
    assert synth.styling_config.task == "answer questions"


class _Completions:
    """A fake OpenAI completions endpoint: returns the queued replies in order."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        text = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
        )


class _Row(BaseModel):
    data: list[str]


def _model_with(replies: list[str]) -> tuple[LiteLlmModel, _Completions]:
    completions = _Completions(replies)
    model = LiteLlmModel("test-model", "http://localhost:4000", "sk-test")
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return model, completions


def test_generate_returns_a_schema_instance_from_fenced_json():
    model, completions = _model_with(['Sure, here it is:\n```json\n{"data": ["a", "b"]}\n```'])

    row = model.generate("Write rows.", schema=_Row)

    assert isinstance(row, _Row)
    assert row.data == ["a", "b"]
    assert "JSON schema" in completions.prompts[0]


def test_generate_retries_an_invalid_schema_reply_once():
    model, completions = _model_with(["not json at all", '{"data": ["a"]}'])

    row = model.generate("Write rows.", schema=_Row)

    assert row.data == ["a"]
    assert len(completions.prompts) == 2
    assert "Your previous reply was invalid" in completions.prompts[1]


def test_generate_without_a_schema_returns_the_text():
    model, _ = _model_with(["plain answer"])
    assert model.generate("Ask something.") == "plain answer"
