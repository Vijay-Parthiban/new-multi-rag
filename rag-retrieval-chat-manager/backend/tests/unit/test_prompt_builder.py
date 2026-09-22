from generation_core.prompt_builder import NO_SOURCES_ANSWER, build_rag_prompt
from rag_shared.types import RerankedChunk


def _chunk(content: str) -> RerankedChunk:
    return RerankedChunk(
        id="1",
        content=content,
        source_type="web_scrape",
        source_id="job-1",
        source_locator="https://example.com/page",
        chunk_index=0,
        chunk_type="text",
        retrieval_score=0.9,
        rerank_score=0.95,
    )


def test_build_rag_prompt_instructs_no_sources_when_context_empty() -> None:
    messages = build_rag_prompt("What is the refund policy?", [])
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert "Do not guess" in system
    assert "could not find relevant sources" in system
    assert "No sources were retrieved" in user
    assert NO_SOURCES_ANSWER.startswith("I could not find")


def test_build_rag_prompt_includes_chunk_context() -> None:
    messages = build_rag_prompt("What is HTML?", [_chunk("HTML is markup.")])
    user = messages[1]["content"]

    assert "[1] Source: https://example.com/page" in user
    assert "HTML is markup." in user


def test_build_rag_prompt_without_history_is_unchanged() -> None:
    """The no-session path must produce exactly the two messages it always did."""
    assert [m["role"] for m in build_rag_prompt("Q", [])] == ["system", "user"]
    assert [m["role"] for m in build_rag_prompt("Q", [], history=[])] == ["system", "user"]
    assert [m["role"] for m in build_rag_prompt("Q", [], history=None)] == ["system", "user"]


def test_build_rag_prompt_places_history_between_system_and_context() -> None:
    history = [
        {"role": "user", "content": "Who is the candidate?"},
        {"role": "assistant", "content": "Alice Smith."},
    ]
    messages = build_rag_prompt("Where does she live?", [_chunk("Alice lives in Pune.")], history=history)

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "Who is the candidate?"
    assert messages[2]["content"] == "Alice Smith."
    # The context and the question stay in the final message, so citations still
    # point at the passages and the grounding rules still apply to the question.
    assert "Alice lives in Pune." in messages[3]["content"]
    assert "Where does she live?" in messages[3]["content"]


def test_build_query_rewrite_prompt_carries_the_transcript() -> None:
    from generation_core.prompt_builder import build_query_rewrite_prompt

    messages = build_query_rewrite_prompt(
        "and her address?",
        [
            {"role": "user", "content": "Who is the candidate?"},
            {"role": "assistant", "content": "Alice Smith."},
        ],
    )

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Do not answer the question" in messages[0]["content"]
    assert "User: Who is the candidate?" in messages[1]["content"]
    assert "Assistant: Alice Smith." in messages[1]["content"]
    assert "Follow-up question: and her address?" in messages[1]["content"]


def test_build_query_rewrite_prompt_handles_empty_history() -> None:
    from generation_core.prompt_builder import build_query_rewrite_prompt

    messages = build_query_rewrite_prompt("standalone?", [])
    assert "(No earlier turns.)" in messages[1]["content"]
