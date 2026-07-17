from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from rag_shared.config import Settings

logger = logging.getLogger(__name__)

EVAL_LABELS = frozenset({"correct", "partially_correct", "incorrect"})
SKIP_PRECISION_RECALL_CATEGORIES = frozenset({"out_of_corpus", "unanswerable"})

_ragas_openai_client: AsyncOpenAI | None = None


def _ragas_litellm_proxy_url(settings: "Settings") -> str:
    return (
        os.getenv("LITELLM_PROXY")
        or os.getenv("LITELLM_BASE_URL")
        or settings.litellm_base_url
    ).rstrip("/")


def _ragas_litellm_api_key(settings: "Settings") -> str:
    return (
        os.getenv("LITELLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or settings.openai_api_key
    )


def _ragas_openai_v1_base_url(settings: "Settings") -> str:
    base = _ragas_litellm_proxy_url(settings)
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def get_ragas_openai_client(settings: "Settings") -> "AsyncOpenAI":
    global _ragas_openai_client
    if _ragas_openai_client is None:
        from openai import AsyncOpenAI

        _ragas_openai_client = AsyncOpenAI(
            base_url=_ragas_openai_v1_base_url(settings),
            api_key=_ragas_litellm_api_key(settings),
        )
        logger.info(
            "ragas_openai_client_ready base_url=%s",
            _ragas_openai_v1_base_url(settings),
        )
    return _ragas_openai_client


def reset_ragas_openai_client() -> None:
    global _ragas_openai_client
    _ragas_openai_client = None


def build_ragas_openai_client(settings: "Settings"):
    return get_ragas_openai_client(settings)


def build_ragas_llm(settings: "Settings"):
    from ragas.llms import llm_factory

    return llm_factory(
        settings.ragas_judge_model,
        client=build_ragas_openai_client(settings),
    )


def build_ragas_embeddings(settings: "Settings"):
    from ragas.embeddings import embedding_factory

    return embedding_factory(
        "openai",
        model=settings.embedding_model,
        client=build_ragas_openai_client(settings),
        interface="modern",
    )


def _score_value(result: object, *, metric_name: str) -> float | None:
    if result is None:
        return None
    if isinstance(result, BaseException):
        logger.warning("RAGAS %s failed: %s", metric_name, result)
        return None
    value = getattr(result, "value", result)
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _should_skip_precision_recall(*, label: str | None, category: str | None) -> bool:
    if label == "incorrect":
        return True
    return category in SKIP_PRECISION_RECALL_CATEGORIES


def _normalize_contexts(contexts: list[str]) -> list[str]:
    return [str(c).strip() for c in contexts if c and str(c).strip()]


async def calculate_retrieval_ragas_async(
    settings: "Settings",
    *,
    question: str,
    contexts: list[str],
    reference: str,
    label: str | None = None,
    category: str | None = None,
    include_context_recall: bool = True,
) -> dict[str, float | None]:
    """RAGAS retrieval metrics: context_precision and context_recall."""
    from ragas.metrics.collections import ContextPrecision, ContextRecall

    if not settings.ragas_enabled:
        return {}

    if _should_skip_precision_recall(label=label, category=category):
        return {}

    contexts = _normalize_contexts(contexts)
    reference = reference.strip()
    if not contexts or not reference:
        logger.warning("Skipping retrieval RAGAS — missing contexts or reference")
        return {}

    llm = build_ragas_llm(settings)
    precision_scorer = ContextPrecision(llm=llm)
    recall_scorer = ContextRecall(llm=llm)

    # ragas>=0.4 collections metrics use ascore(**fields), not single_turn_ascore(sample)
    precision_result = await precision_scorer.ascore(
        user_input=question,
        reference=reference,
        retrieved_contexts=contexts,
    )
    scores: dict[str, float | None] = {
        "context_precision": _score_value(precision_result, metric_name="context_precision"),
    }
    if include_context_recall:
        recall_result = await recall_scorer.ascore(
            user_input=question,
            reference=reference,
            retrieved_contexts=contexts,
        )
        scores["context_recall"] = _score_value(recall_result, metric_name="context_recall")
    return scores


async def calculate_generation_ragas_async(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float | None]:
    """RAGAS generation metric: faithfulness and answer_relevancy."""
    from ragas.metrics.collections import Faithfulness, AnswerRelevancy

    if not settings.ragas_enabled:
        return {}

    if not answer or not answer.strip():
        logger.warning("Skipping faithfulness — answer is empty")
        return {}

    contexts = _normalize_contexts(contexts)
    if not contexts:
        logger.warning("Skipping generation metrics — no contexts")
        return {}

    llm = build_ragas_llm(settings)

    faithfulness_scorer = Faithfulness(llm=llm)
    faith_task = faithfulness_scorer.ascore(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )

    relevancy_scorer = AnswerRelevancy(llm=llm, embeddings=build_ragas_embeddings(settings))
    # AnswerRelevancy.ascore only accepts user_input + response in ragas 0.4
    rel_task = relevancy_scorer.ascore(
        user_input=question,
        response=answer,
    )

    results = await asyncio.gather(faith_task, rel_task, return_exceptions=True)

    output: dict[str, float | None] = {}
    f_val = _score_value(results[0], metric_name="faithfulness")
    if f_val is not None:
        output["faithfulness"] = f_val

    r_val = _score_value(results[1], metric_name="answer_relevancy")
    if r_val is not None:
        output["answer_relevancy"] = r_val

    return output


async def calculate_eval_metrics_async(
    settings: "Settings",
    *,
    question: str,
    contexts: list[str],
    answer: str,
    ground_truth: str | None = None,
    label: str | None = None,
    category: str | None = None,
    include_context_recall: bool = True,
) -> dict[str, float | None]:
    """Combined RAGAS metrics for backward-compatible golden eval helpers."""
    reference = (ground_truth or "").strip() or answer.strip()
    retrieval_scores, generation_scores = await asyncio.gather(
        calculate_retrieval_ragas_async(
            settings,
            question=question,
            contexts=contexts,
            reference=reference,
            label=label,
            category=category,
            include_context_recall=include_context_recall,
        ),
        calculate_generation_ragas_async(
            settings,
            question=question,
            answer=answer,
            contexts=contexts,
        ),
    )
    if _should_skip_precision_recall(label=label, category=category):
        return generation_scores
    return {**retrieval_scores, **generation_scores}


def compute_retrieval_ragas_metrics(
    settings: "Settings",
    *,
    question: str,
    contexts: list[str],
    reference: str,
    label: str | None = None,
    category: str | None = None,
    include_context_recall: bool = True,
) -> dict[str, float | None]:
    return asyncio.run(
        calculate_retrieval_ragas_async(
            settings,
            question=question,
            contexts=contexts,
            reference=reference,
            label=label,
            category=category,
            include_context_recall=include_context_recall,
        )
    )


def compute_generation_ragas_metrics(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float | None]:
    return asyncio.run(
        calculate_generation_ragas_async(
            settings,
            question=question,
            answer=answer,
            contexts=contexts,
        )
    )


async def calculate_faithfulness_ragas_async(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float | None]:
    """RAGAS faithfulness metric only."""
    from ragas.metrics.collections import Faithfulness

    if not settings.ragas_enabled:
        return {}

    if not answer or not answer.strip():
        logger.warning("Skipping faithfulness — answer is empty")
        return {}

    contexts = _normalize_contexts(contexts)
    if not contexts:
        logger.warning("Skipping faithfulness — no contexts")
        return {}

    llm = build_ragas_llm(settings)
    faithfulness_scorer = Faithfulness(llm=llm)
    result = await faithfulness_scorer.ascore(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )
    f_val = _score_value(result, metric_name="faithfulness")
    if f_val is not None:
        return {"faithfulness": f_val}
    return {}


def compute_faithfulness_metrics(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float | None]:
    return asyncio.run(
        calculate_faithfulness_ragas_async(
            settings,
            question=question,
            answer=answer,
            contexts=contexts,
        )
    )


def compute_generation_metrics(
    settings: "Settings",
    *,
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str | None = None,
    label: str | None = None,
    category: str | None = None,
    include_context_recall: bool = True,
) -> dict[str, float | None]:
    """Sync wrapper used by eval worker and golden-item runner."""
    return asyncio.run(
        calculate_eval_metrics_async(
            settings,
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
            label=label,
            category=category,
            include_context_recall=include_context_recall,
        )
    )
