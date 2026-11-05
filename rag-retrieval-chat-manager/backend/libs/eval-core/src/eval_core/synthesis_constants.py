"""The evolution names, in a module with no heavy imports.

`synthesis.py` imports deepeval, openai and qdrant-client at module level. rag-api reads
these names only to validate a request, and pulling the synthesiser into the API process
for a tuple is a startup cost with no use. Both sides import from here instead.
"""

from __future__ import annotations

EVOLUTION_NAMES = (
    "reasoning",
    "multicontext",
    "concretizing",
    "constrained",
    "comparative",
    "hypothetical",
    "in_breadth",
)
# The four that leave the question answerable from the same context. `reasoning` and
# `hypothetical` drift away from the corpus, and `in_breadth` broadens the topic, so a
# retrieval row built with them has no source in the product.
RAG_SAFE_EVOLUTIONS = ("multicontext", "concretizing", "constrained", "comparative")

# The config key that holds each dataset kind's settings, and the word used for it.
KIND_CONFIG_KEY = {"single_turn": "single", "multi_turn": "multi"}
KIND_WORD = {"single_turn": "single", "multi_turn": "multi"}

__all__ = ["EVOLUTION_NAMES", "RAG_SAFE_EVOLUTIONS", "KIND_CONFIG_KEY", "KIND_WORD"]
