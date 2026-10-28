"""The judge's output budget.

Every RAGAS metric answers in structured JSON, and a provider default below the longest
answer truncates it. RAGAS then reports the metric as failed rather than as a wrong score,
so a run stores a score for one row and nothing for the next. This pins the budget so the
failure cannot come back unnoticed.
"""

from __future__ import annotations

from eval_core import ragas_client


def test_the_judge_gets_an_output_budget(monkeypatch):
    seen: dict = {}

    def fake_factory(model, **kwargs):
        seen["model"] = model
        seen.update(kwargs)
        return object()

    import ragas.llms

    monkeypatch.setattr(ragas.llms, "llm_factory", fake_factory)
    monkeypatch.setattr(
        ragas_client, "build_ragas_openai_client", lambda settings: "client"
    )

    ragas_client.build_ragas_llm(object(), "a-judge")

    assert seen["model"] == "a-judge"
    assert seen["max_tokens"] == ragas_client.JUDGE_MAX_TOKENS
    # 4096 was measured to truncate AnswerCorrectness on a five-passage resume row, which
    # turned a real score into a missing one. The budget must stay above the longest
    # statement list a row produces.
    assert ragas_client.JUDGE_MAX_TOKENS >= 8192


def test_a_metric_that_fails_is_a_missing_score_not_a_zero():
    """A failed metric leaves its key out, so the mean covers only the rows that scored."""
    assert ragas_client._score_value(RuntimeError("truncated"), metric_name="faithfulness") is None
    assert ragas_client._score_value(None, metric_name="faithfulness") is None
    assert ragas_client._score_value(0.0, metric_name="faithfulness") == 0.0
