from __future__ import annotations

import logging
from pathlib import Path
from rag_shared.prompt_overrides import read_override

logger = logging.getLogger(__name__)

_CACHE: dict[str, str] = {}

DEFAULT_PROMPTS: dict[str, str] = {
    "rag_synthesis": (
        "You are a helpful assistant. Use the following context documents to answer the question.\n\n"
        "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    ),
    "system_prompt": "You are an AI assistant powered by Multi-RAG.",
}


def clear_prompt_cache() -> None:
    _CACHE.clear()


def load_packaged_prompt(name: str) -> str:
    pkg_dir = Path(__file__).parent / "prompts"
    prompt_file = pkg_dir / (name if name.endswith(".txt") else f"{name}.txt")
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    clean_name = name.removesuffix(".txt")
    if clean_name in DEFAULT_PROMPTS:
        return DEFAULT_PROMPTS[clean_name]
    return f"Prompt template '{name}' context:\n{{context}}\nQuestion:\n{{question}}"


def load_prompt(name: str) -> str:
    override = read_override("generation_core", name)
    if override is not None:
        return override
    if name in _CACHE:
        return _CACHE[name]
    content = load_packaged_prompt(name)
    _CACHE[name] = content
    return content
