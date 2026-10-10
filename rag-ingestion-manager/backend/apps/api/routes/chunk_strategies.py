"""The chunk strategy catalogue: the eight strategies and the settings each one takes.

This module is the single source of truth for the strategy list. The profile form
renders what ``GET /api/ingestion-profiles/chunk-strategies`` returns, so a new
strategy is one entry here plus one branch in ``text_splitter``, and no frontend
change.

A parameter carries a ``scope``:

``profile``   the value is a column of the Ingestion Profile itself, so it sits in
              the create and update request beside ``name``.
``strategy``  the value lives inside the profile's ``chunk_config`` JSON object,
              because only the strategy that declares it reads it.
"""

from __future__ import annotations

from typing import Any

from src.shared.db.models import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_GROUP_WINDOW = "Window"
_GROUP_STRATEGY = "Strategy"


def _param(
    key: str,
    *,
    label: str,
    scope: str,
    field_type: str = "number",
    description: str = "",
    required: bool = False,
    group: str = _GROUP_STRATEGY,
    min_value: float | None = None,
    max_value: float | None = None,
    options: list[dict[str, str]] | None = None,
    model_kind: str | None = None,
    default: Any = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": field_type,
        "description": description,
        "required": required,
        "group": group,
        "min": min_value,
        "max": max_value,
        "options": options,
        "model_kind": model_kind,
        "scope": scope,
        "default": default,
    }


def _window_params(
    *, size_label: str = "Chunk Size (characters)", overlap_label: str = "Chunk Overlap (characters)"
) -> list[dict[str, Any]]:
    """The size window. Every strategy except the two that fix their own unit."""
    return [
        _param(
            "chunk_size",
            label=size_label,
            scope="profile",
            group=_GROUP_WINDOW,
            description="The window one chunk fills. 1000 characters suits most prose.",
            min_value=100,
            max_value=8000,
            default=DEFAULT_CHUNK_SIZE,
        ),
        _param(
            "chunk_overlap",
            label=overlap_label,
            scope="profile",
            group=_GROUP_WINDOW,
            description="Characters repeated at the start of the next chunk, so a sentence across the boundary is not lost.",
            min_value=0,
            max_value=2000,
            default=DEFAULT_CHUNK_OVERLAP,
        ),
    ]


CHUNK_STRATEGY_SPECS: list[dict[str, Any]] = [
    {
        "value": "recursive",
        "label": "Recursive Chunking",
        "description": "Splits on headings and blank lines, then packs the pieces into the window. The default, and the safest choice for a mixed set of documents.",
        "params": _window_params(),
    },
    {
        "value": "fixed",
        "label": "Fixed-Size Chunking",
        "description": "Cuts every window without looking at the text. Even chunks and fast to build, but a sentence can land in two chunks.",
        "params": _window_params(),
    },
    {
        "value": "section",
        "label": "Structure-Aware / Document-Aware Chunking",
        "description": "One chunk per heading or paragraph, so a section stays whole. A PDF uses the document's own layout blocks, which keeps a table in one chunk.",
        "params": _window_params(),
    },
    {
        "value": "context_aware",
        "label": "Semantic Chunking",
        "description": "Measures how much each sentence resembles the next one and starts a new chunk at a topic change. One embedding request per page.",
        "params": [
            *_window_params(size_label="Largest Chunk Size (characters)"),
            _param(
                "semantic_threshold_type",
                label="Breakpoint Type",
                scope="strategy",
                field_type="select",
                group="Breakpoints",
                description="How the topic-change threshold is measured over the page.",
                options=[
                    {"value": "standard_deviation", "label": "Standard deviation below the page mean"},
                    {"value": "percentile", "label": "Percentile of the page similarities"},
                    {"value": "interquartile", "label": "Interquartile range of the page similarities"},
                ],
                default="standard_deviation",
            ),
            _param(
                "semantic_threshold_amount",
                label="Breakpoint Amount",
                scope="strategy",
                group="Breakpoints",
                description="0.5 makes many small groups, 3.0 makes a few large ones.",
                min_value=0.5,
                max_value=3.0,
                default=1.0,
            ),
        ],
    },
    {
        "value": "parent_child",
        "label": "Parent-Child / Hierarchical Chunking",
        "description": "Stores a large parent chunk and the small child chunks cut from it. A search hit returns the child plus the surrounding parent text.",
        "params": [
            *_window_params(
                size_label="Parent Chunk Size (characters)",
                overlap_label="Parent Chunk Overlap (characters)",
            ),
            _param(
                "child_chunk_size",
                label="Child Chunk Size (characters)",
                scope="strategy",
                description="0 derives one third of the parent size, at least 80 characters.",
                min_value=0,
                max_value=2000,
                default=0,
            ),
            _param(
                "child_overlap",
                label="Child Chunk Overlap (characters)",
                scope="strategy",
                description="Characters repeated at the start of the next child chunk.",
                min_value=0,
                max_value=500,
                default=0,
            ),
        ],
    },
    {
        "value": "contextual",
        "label": "Contextual Chunking",
        "description": "Asks a chat model for one short sentence that places each chunk in its document, then stores that sentence in front of the chunk. One model call per chunk.",
        "params": [
            *_window_params(),
            _param(
                "context_model",
                label="Context Model",
                scope="strategy",
                field_type="model",
                model_kind="chat",
                required=True,
                description="The chat model that writes the context sentence.",
                default=None,
            ),
            _param(
                "context_max_tokens",
                label="Context Size (tokens)",
                scope="strategy",
                description="The token ceiling for one context sentence.",
                min_value=50,
                max_value=500,
                default=100,
            ),
        ],
    },
    {
        "value": "page_level",
        "label": "Page-Level Chunking",
        "description": "One chunk per page, which keeps a page self-contained. A page over the limit is cut on paragraph boundaries.",
        "params": [
            _param(
                "max_page_chars",
                label="Max Page Characters",
                scope="strategy",
                description="0 never splits a page; a larger page is cut on paragraph boundaries.",
                min_value=0,
                max_value=20000,
                default=0,
            ),
        ],
    },
    {
        "value": "sentence_window",
        "label": "Sentence-Window Chunking",
        "description": "Stores each sentence on its own plus the window of sentences around it, so a matched sentence can return its neighbours.",
        "params": [
            _param(
                "window_sentences",
                label="Window Sentences",
                scope="strategy",
                description="Sentences stored on each side of the sentence that matched.",
                min_value=1,
                max_value=10,
                default=2,
            ),
        ],
    },
]

_SPEC_BY_VALUE = {spec["value"]: spec for spec in CHUNK_STRATEGY_SPECS}


def chunk_strategy_options() -> list[dict[str, Any]]:
    """The catalogue the profile form renders, in display order."""
    return CHUNK_STRATEGY_SPECS


def default_chunk_config(value: str) -> dict[str, Any]:
    """The strategy-scope settings with their declared defaults."""
    spec = _SPEC_BY_VALUE.get(value)
    if spec is None:
        return {}
    return {
        param["key"]: param["default"]
        for param in spec["params"]
        if param["scope"] == "strategy"
    }


def validate_chunk_config(value: str, config: dict[str, Any] | None) -> list[str]:
    """Messages for a ``chunk_config`` that does not fit its strategy.

    An empty list means valid. An unknown strategy is not checked here: the
    request model already rejects it, and a stored row may name a strategy this
    module no longer offers.
    """
    spec = _SPEC_BY_VALUE.get(value)
    if spec is None or not config:
        return []
    params = {
        param["key"]: param for param in spec["params"] if param["scope"] == "strategy"
    }
    messages: list[str] = []
    for key, raw in config.items():
        param = params.get(key)
        if param is None:
            messages.append(f"'{key}' is not a setting of the '{value}' chunk strategy.")
            continue
        if raw is None or raw == "":
            continue
        if param["type"] == "select":
            allowed = {option["value"] for option in param["options"] or []}
            if str(raw) not in allowed:
                messages.append(
                    f"'{raw}' is not a value of '{param['label']}'. "
                    f"Use one of: {', '.join(sorted(allowed))}."
                )
            continue
        if param["type"] == "model":
            # A model name is free text. The proxy list is a suggestion, and a
            # name the proxy does not serve yet must still be storable.
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            messages.append(f"'{param['label']}' must be a number.")
            continue
        low, high = param["min"], param["max"]
        if low is not None and number < low:
            messages.append(f"'{param['label']}' must be at least {low:g}.")
        elif high is not None and number > high:
            messages.append(f"'{param['label']}' must be at most {high:g}.")
    return messages
