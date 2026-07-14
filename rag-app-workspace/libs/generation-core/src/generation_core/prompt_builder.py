from __future__ import annotations

from rag_shared.types import RerankedChunk

NO_SOURCES_ANSWER = (
    "I could not find any relevant sources in the knowledge base to answer this question."
)

RAG_SYSTEM_PROMPT = (
    "You are a helpful RAG assistant. Answer the user's question using ONLY the "
    "numbered context passages provided in the user message.\n\n"
    "Rules:\n"
    "- If no context passages are provided, or none of them contain information "
    "relevant to the question, respond clearly that you could not find relevant "
    "sources to answer the question. Do not guess, invent facts, or use outside knowledge.\n"
    "- If the passages only partially answer the question, answer what is supported "
    "and state what information is missing.\n"
    "- When you use information from a passage, cite its source number."
)

FUSION_SYSTEM_PROMPT = (
    "You are a helpful assistant. Combine the partial answers into one coherent "
    "response to the user's question. Prefer facts supported by the partial answers. "
    "If they conflict, note the uncertainty. If neither partial answer contains "
    "relevant information, say clearly that no relevant sources were found to "
    "answer the question."
)


def build_rag_prompt(query: str, chunks: list[RerankedChunk]) -> list[dict[str, str]]:
    if chunks:
        context_parts = []
        for i, chunk in enumerate(chunks, start=1):
            locator = chunk.source_locator or "unknown"
            context_parts.append(f"[{i}] Source: {locator}\n{chunk.content}")
        context = "\n\n".join(context_parts)
    else:
        context = "(No sources were retrieved for this question.)"

    user = f"Context:\n{context}\n\nQuestion: {query}"
    return [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_fusion_prompt(
    query: str,
    *,
    text_answer: str | None = None,
    vision_answer: str | None = None,
) -> list[dict[str, str]]:
    sections: list[str] = []
    if text_answer:
        sections.append(f"Text-source answer:\n{text_answer}")
    if vision_answer:
        sections.append(f"Image-source answer:\n{vision_answer}")

    combined = "\n\n".join(sections) if sections else "(No partial answers were produced.)"
    user = f"{combined}\n\nQuestion: {query}\n\nFinal answer:"
    return [
        {"role": "system", "content": FUSION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
