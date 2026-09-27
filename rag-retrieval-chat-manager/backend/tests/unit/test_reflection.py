"""The generation-pattern graders.

The two rules that matter are failure rules, so they get the tests:

- a grader that cannot be trusted keeps every passage, because an outage must
  degrade to plain RAG and never to an empty context;
- nothing above the threshold keeps nothing, because the corrective pattern's
  whole point is that an unanswered question beats a fabricated answer.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rag_core.reflection import _parse_scores, answer_is_grounded, grade_relevance
from rag_shared.config import Settings

CHUNKS = [
    SimpleNamespace(content="The Code of Conduct governs employee conduct."),
    SimpleNamespace(content="The office is closed on public holidays."),
    SimpleNamespace(content="Community investment is a core value."),
]


def _reply(content: str, finish_reason: str = "stop"):
    """A stand-in for the OpenAI response object."""
    response = MagicMock()
    response.choices = [
        SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
    ]
    return response


def _with_reply(content: str, finish_reason: str = "stop"):
    client = MagicMock()
    client.chat.completions.create.return_value = _reply(content, finish_reason)
    return patch("rag_core.reflection._client", return_value=client)


def _with_failure(exc: Exception):
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return patch("rag_core.reflection._client", return_value=client)


def test_parse_scores_reads_every_line():
    assert _parse_scores("0: 0.9\n1: 0.2\n2: 1.0", 3) == [0.9, 0.2, 1.0]


def test_parse_scores_rejects_a_partial_reply():
    # A missing score must not read as zero: that would drop a passage the model
    # never considered.
    assert _parse_scores("0: 0.9\n2: 1.0", 3) is None


def test_parse_scores_rejects_prose():
    assert _parse_scores("All three passages look relevant to me.", 3) is None


def test_parse_scores_clamps_and_ignores_out_of_range():
    assert _parse_scores("0: 5\n1: -2\n2: 0.5\n9: 0.9", 3) == [1.0, 0.0, 0.5]


def test_grading_keeps_only_passages_above_the_threshold():
    with _with_reply("0: 0.9\n1: 0.1\n2: 0.8"):
        result = grade_relevance(Settings(), query="conduct", chunks=CHUNKS, model="m")
    assert result.scored is True
    assert [c.content for c in result.kept] == [CHUNKS[0].content, CHUNKS[2].content]
    assert result.best_score == 0.9


def test_grading_abstains_when_nothing_scores_well():
    with _with_reply("0: 0.1\n1: 0.2\n2: 0.0"):
        result = grade_relevance(Settings(), query="unrelated", chunks=CHUNKS, model="m")
    # An empty list is a legal outcome, not a failure.
    assert result.kept == []
    assert result.scored is True


def test_grading_keeps_everything_when_the_call_fails():
    with _with_failure(RuntimeError("litellm unreachable")):
        result = grade_relevance(Settings(), query="conduct", chunks=CHUNKS, model="m")
    assert result.kept == CHUNKS
    assert result.scored is False


def test_grading_keeps_everything_when_the_reply_is_unparseable():
    with _with_reply("I cannot help with that."):
        result = grade_relevance(Settings(), query="conduct", chunks=CHUNKS, model="m")
    assert result.kept == CHUNKS
    assert result.scored is False


def test_grading_with_no_chunks_does_not_call_the_model():
    with _with_reply("") as patched:
        result = grade_relevance(Settings(), query="conduct", chunks=[], model="m")
    assert result.kept == []
    patched.assert_not_called()


def test_grounding_detects_an_unsupported_answer():
    with _with_reply("UNGROUNDED"):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is False


def test_grounding_accepts_a_supported_answer():
    with _with_reply("GROUNDED"):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is True


def test_grounding_returns_none_on_failure_so_the_answer_stands():
    with _with_failure(RuntimeError("boom")):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is None


def test_grounding_returns_none_on_a_vague_verdict():
    # Only a definite UNGROUNDED may trigger a rewrite.
    with _with_reply("The answer seems fine."):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is None


def test_grounding_reads_a_wrapped_verdict():
    # A reasoning model may put the verdict in a sentence, so the check scans.
    with _with_reply("Verdict: GROUNDED"):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is True


def test_grounding_does_not_confuse_ungrounded_with_grounded():
    # "UNGROUNDED" contains "GROUNDED", so the longer word has to win.
    with _with_reply("The answer is UNGROUNDED."):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is False


def test_grounding_returns_none_on_an_empty_reply():
    # This is what a reasoning model returns when the token budget runs out before
    # it emits anything. The answer must stand rather than be judged unsupported.
    with _with_reply(""):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is None


def test_grounding_returns_none_when_the_model_was_cut_off():
    # finish_reason=length with no content means the budget was too small, which is
    # the failure that silently disables the check. It must not read as supported.
    with _with_reply("", finish_reason="length"):
        assert answer_is_grounded(
            Settings(), query="q", answer="a", chunks=CHUNKS, model="m"
        ) is None
