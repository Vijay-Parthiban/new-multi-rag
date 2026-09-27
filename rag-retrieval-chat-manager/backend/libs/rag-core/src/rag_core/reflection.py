"""Prompt-based graders for the generation patterns.

Self-reflective and corrective RAG both put a second model in the loop: one that
grades the retrieved passages before the answer is written, and (for the
self-reflective pattern only) one that checks the answer is actually grounded in
those passages.

The published systems train a dedicated critic with reflection tokens. That is not
needed here: the four questions those tokens answer, relevance and grounding among
them, survive in production as ordinary prompts to the chat model. See
``docs/14`` for the sources.

Two rules shape this module, and both exist so a bad grader can never be worse
than no grader:

1. **A failure keeps everything.** A call that errors, times out or returns
   something unparseable yields every passage, unchanged. A grader outage must
   degrade to plain RAG, never to an empty context.
2. **An empty pass is legal.** The corrective pattern answers "the sources do not
   cover this" when nothing scores well. That is a real answer, not a failure.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from openai import OpenAI
from rag_shared.config import Settings

logger = logging.getLogger(__name__)


def _client(settings: Settings) -> OpenAI:
    """The same OpenAI-compatible client the generator talks to, at the proxy."""
    return OpenAI(base_url=settings.litellm_base_url, api_key=settings.openai_api_key)

# Both graders are classifications, so their replies are short, but the limit cannot
# be small: a reasoning model spends the budget on its own preamble before it emits
# anything, and it returns empty content with finish_reason=length when it runs out.
# Measured against Gpt-oss-20b and a realistic prompt (two long passages plus a long
# answer, about 3.1k characters): 256 truncates, 512 answers. 1024 is used for
# headroom, because the passage count and length vary per turn.
_GRADE_MAX_TOKENS = 1024
_GROUNDING_MAX_TOKENS = 1024

_VERDICT_RE = re.compile(r"\b(UNGROUNDED|GROUNDED)\b")

_RELEVANCE_SYSTEM = """You score how relevant each numbered passage is to a question.

Reply with one line per passage, in this exact format and nothing else:
<number>: <score>

The score is a number from 0 to 1:
1.0 means the passage answers the question directly.
0.0 means the passage is unrelated.

Judge only relevance to the question. Do not use outside knowledge."""

_GROUNDING_SYSTEM = """You check whether an answer is supported by numbered passages.

Reply with exactly one word: GROUNDED or UNGROUNDED.

GROUNDED means every factual claim in the answer appears in a passage.
UNGROUNDED means the answer adds a fact the passages do not contain.
Judge only support, not correctness or style."""

_LINE_RE = re.compile(r"^\s*(\d+)\s*[:=-]\s*(-?\d+(?:\.\d+)?)\s*$")


@dataclass
class Grading:
    """What the relevance grader decided.

    ``kept`` is in input order, so the caller's ranking survives. ``scored`` is
    False when the grader could not be trusted and every passage was kept, which
    is what the trace records.
    """

    kept: list
    scored: bool
    best_score: float | None


def grade_relevance(
    settings: Settings,
    *,
    query: str,
    chunks: list,
    model: str | None = None,
    threshold: float | None = None,
) -> Grading:
    """Keep the passages that answer the question, by the model's own score.

    A passage scoring at or above ``threshold`` is kept. When nothing reaches it,
    ``kept`` is empty and the caller abstains, which is the corrective pattern's
    whole point: an unanswered question beats a fabricated answer.
    """
    if not chunks:
        return Grading(kept=[], scored=True, best_score=None)

    cut = settings.relevance_threshold if threshold is None else threshold
    numbered = "\n\n".join(
        f"{i}. {(getattr(c, 'content', '') or '').strip()}" for i, c in enumerate(chunks)
    )
    prompt = [{"role": "system", "content": _RELEVANCE_SYSTEM}]
    prompt.append({"role": "user", "content": f"Question: {query}\n\nPassages:\n{numbered}"})

    try:
        response = _client(settings).chat.completions.create(
            model=model or settings.chat_model,
            messages=prompt,
            max_tokens=_GRADE_MAX_TOKENS,
            temperature=0.0,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001 - a grader must not fail the turn
        logger.warning("relevance grading call failed error=%s keeping_all=%s", exc, len(chunks))
        return Grading(kept=list(chunks), scored=False, best_score=None)

    scores = _parse_scores(raw, len(chunks))
    if scores is None:
        logger.warning("relevance grading unparseable keeping_all=%s", len(chunks))
        return Grading(kept=list(chunks), scored=False, best_score=None)

    kept = [c for i, c in enumerate(chunks) if scores[i] >= cut]
    best = max(scores) if scores else None
    logger.info(
        "relevance_graded candidates=%s kept=%s best=%s threshold=%s",
        len(chunks),
        len(kept),
        best,
        cut,
    )
    return Grading(kept=kept, scored=True, best_score=best)


def _parse_scores(raw: str, expected: int) -> list[float] | None:
    """One clamped score per passage, or None when the reply cannot be trusted.

    A reply that scores only some of the passages is rejected outright rather than
    guessed at, because a missing score would otherwise read as zero and silently
    drop a passage the model never considered.
    """
    by_index: dict[int, float] = {}
    for line in raw.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        index = int(match.group(1))
        if 0 <= index < expected:
            by_index[index] = max(0.0, min(1.0, float(match.group(2))))
    if len(by_index) != expected:
        return None
    return [by_index[i] for i in range(expected)]


def answer_is_grounded(
    settings: Settings,
    *,
    query: str,
    answer: str,
    chunks: list,
    model: str | None = None,
) -> bool | None:
    """Whether the answer is supported by the passages.

    Returns None when the check could not run, which the caller reads as "leave the
    answer alone". Only a definite UNGROUNDED verdict triggers a rewrite.
    """
    if not answer.strip() or not chunks:
        return None

    numbered = "\n\n".join(
        f"{i}. {(getattr(c, 'content', '') or '').strip()}" for i, c in enumerate(chunks)
    )
    prompt = [
        {"role": "system", "content": _GROUNDING_SYSTEM},
        {"role": "user", "content": f"Question: {query}\n\nPassages:\n{numbered}\n\nAnswer: {answer}"},
    ]
    try:
        response = _client(settings).chat.completions.create(
            model=model or settings.chat_model,
            messages=prompt,
            max_tokens=_GROUNDING_MAX_TOKENS,
            temperature=0.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        finish = response.choices[0].finish_reason
    except Exception as exc:  # noqa: BLE001 - a failed check must not fail the turn
        logger.warning("grounding check failed error=%s", exc)
        return None

    if not raw and finish == "length":
        # The specific failure a reasoning model shows when the budget is too small.
        # Worth its own line, because the symptom is an empty string rather than an
        # error and it silently disables the check.
        logger.warning(
            "grounding check truncated before it answered max_tokens=%s", _GROUNDING_MAX_TOKENS
        )
        return None

    # Scan rather than exact-match: a reasoning model may wrap the verdict in a
    # sentence, and UNGROUNDED is tested first because it contains GROUNDED.
    match = _VERDICT_RE.search(raw.upper())
    if match:
        return match.group(1) == "GROUNDED"
    logger.warning("grounding verdict unparseable verdict=%r", raw[:60])
    return None
