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
