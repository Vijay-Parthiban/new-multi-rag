from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_core.ragas_client import (
    _ragas_openai_v1_base_url,
    _should_skip_precision_recall,
    compute_faithfulness_metrics,
    compute_generation_metrics,
    get_ragas_openai_client,
    reset_ragas_openai_client,
)


class _MetricResult:
    def __init__(self, value: float) -> None:
        self.value = value


@pytest.mark.parametrize(
    ("label", "category", "expected"),
    [
        ("incorrect", None, True),
        (None, "out_of_corpus", True),
        (None, "unanswerable", True),
        ("correct", "factual", False),
        (None, "factual", False),
    ],
)
def test_should_skip_precision_recall(label, category, expected) -> None:
    assert _should_skip_precision_recall(label=label, category=category) is expected


@patch("eval_core.ragas_client.build_ragas_embeddings")
@patch("eval_core.ragas_client.build_ragas_llm")
def test_compute_generation_metrics_skips_precision_recall_for_out_of_corpus(
    mock_llm, mock_embeddings
) -> None:
    mock_llm.return_value = MagicMock()
    mock_embeddings.return_value = MagicMock()
    faith_scorer = MagicMock()
    faith_scorer.ascore = AsyncMock(return_value=_MetricResult(0.8))
    relevancy = MagicMock()
    relevancy.ascore = AsyncMock(return_value=_MetricResult(0.75))

    settings = MagicMock()
    settings.ragas_enabled = True
    settings.ragas_judge_model = "llama-3.3-70b-versatile"

    with (
        patch("ragas.metrics.collections.Faithfulness", return_value=faith_scorer),
        patch("ragas.metrics.collections.AnswerRelevancy", return_value=relevancy),
    ):
        scores = compute_generation_metrics(
            settings,
            question="What is the stock price?",
            answer="I don't know",
            contexts=["Some text"],
            ground_truth="Not in corpus",
            category="out_of_corpus",
        )

    assert scores == {"faithfulness": 0.8, "answer_relevancy": 0.75}
    faith_scorer.ascore.assert_awaited_once()


@patch("eval_core.ragas_client.build_ragas_llm")
def test_compute_retrieval_ragas_metrics_only(mock_llm) -> None:
    from eval_core.ragas_client import compute_retrieval_ragas_metrics

    mock_llm.return_value = MagicMock()
    precision = MagicMock()
    precision.ascore = AsyncMock(return_value=_MetricResult(0.7))
    recall = MagicMock()
    recall.ascore = AsyncMock(return_value=_MetricResult(0.6))

    settings = MagicMock()
    settings.ragas_enabled = True
    settings.ragas_judge_model = "llama-3.3-70b-versatile"

    with (
        patch("ragas.metrics.collections.ContextPrecision", return_value=precision),
        patch("ragas.metrics.collections.ContextRecall", return_value=recall),
    ):
        scores = compute_retrieval_ragas_metrics(
            settings,
            question="What is HTML?",
            contexts=["HTML is markup language."],
            reference="HTML is markup.",
        )

    assert scores == {"context_precision": 0.7, "context_recall": 0.6}
    precision.ascore.assert_awaited_once()
    recall.ascore.assert_awaited_once()


@patch("eval_core.ragas_client.build_ragas_llm")
def test_compute_faithfulness_metrics_only(mock_llm) -> None:
    from eval_core.ragas_client import compute_faithfulness_metrics

    mock_llm.return_value = MagicMock()
    faith = MagicMock()
    faith.ascore = AsyncMock(return_value=_MetricResult(0.9))

    settings = MagicMock()
    settings.ragas_enabled = True
    settings.ragas_judge_model = "llama-3.3-70b-versatile"

    with patch("ragas.metrics.collections.Faithfulness", return_value=faith):
        scores = compute_faithfulness_metrics(
            settings,
            question="What is HTML?",
            answer="HTML is markup.",
            contexts=["HTML is markup language."],
        )

    assert scores == {"faithfulness": 0.9}
    faith.ascore.assert_awaited_once()


@patch("eval_core.ragas_client.build_ragas_embeddings")
@patch("eval_core.ragas_client.build_ragas_llm")
def test_compute_generation_metrics_returns_all_metrics(mock_llm, mock_embeddings) -> None:
    mock_llm.return_value = MagicMock()
    mock_embeddings.return_value = MagicMock()

    precision = MagicMock()
    precision.ascore = AsyncMock(return_value=_MetricResult(0.7))
    recall = MagicMock()
    recall.ascore = AsyncMock(return_value=_MetricResult(0.6))
    faith = MagicMock()
    faith.ascore = AsyncMock(return_value=_MetricResult(0.9))
    relevancy = MagicMock()
    relevancy.ascore = AsyncMock(return_value=_MetricResult(0.85))

    settings = MagicMock()
    settings.ragas_enabled = True
    settings.ragas_judge_model = "llama-3.3-70b-versatile"

    with (
        patch("ragas.metrics.collections.ContextPrecision", return_value=precision),
        patch("ragas.metrics.collections.ContextRecall", return_value=recall),
        patch("ragas.metrics.collections.Faithfulness", return_value=faith),
        patch("ragas.metrics.collections.AnswerRelevancy", return_value=relevancy),
    ):
        scores = compute_generation_metrics(
            settings,
            question="What is HTML?",
            answer="HTML is markup.",
            contexts=["HTML is markup language."],
            ground_truth="HTML is markup.",
            category="factual",
        )

    assert scores == {
        "context_precision": 0.7,
        "context_recall": 0.6,
        "faithfulness": 0.9,
        "answer_relevancy": 0.85,
    }


def test_compute_generation_metrics_disabled_returns_empty() -> None:
    settings = MagicMock()
    settings.ragas_enabled = False
    assert compute_generation_metrics(
        settings,
        question="q",
        answer="a",
        contexts=["c"],
    ) == {}


def test_ragas_openai_v1_base_url_appends_v1() -> None:
    from rag_shared.config import Settings

    settings = Settings(litellm_base_url="http://localhost:4000", openai_api_key="sk-test")
    assert _ragas_openai_v1_base_url(settings) == "http://localhost:4000/v1"


def test_ragas_openai_v1_base_url_prefers_litellm_proxy_env(monkeypatch) -> None:
    from rag_shared.config import Settings

    monkeypatch.setenv("LITELLM_PROXY", "http://proxy:5000")
    settings = Settings(litellm_base_url="http://localhost:4000", openai_api_key="sk-test")
    assert _ragas_openai_v1_base_url(settings) == "http://proxy:5000/v1"


def test_get_ragas_openai_client_uses_v1_base_and_cached_singleton() -> None:
    from rag_shared.config import Settings

    reset_ragas_openai_client()
    settings = Settings(litellm_base_url="http://localhost:4000", openai_api_key="sk-test")
    first = get_ragas_openai_client(settings)
    second = get_ragas_openai_client(settings)
    assert first is second
    assert str(first.base_url).rstrip("/") == "http://localhost:4000/v1"
    reset_ragas_openai_client()
