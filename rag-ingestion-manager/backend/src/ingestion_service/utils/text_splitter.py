"""Chunking strategies for the fanout and the legacy Pipeline path.

Three entry points, because the shapes of output differ:

``chunk_text`` returns a flat list of chunk strings for one page. Five of the
strategies use it.
``chunk_parent_child``, ``chunk_sentence_window`` and ``chunk_page`` return
records instead, because the records of one page are not all the same kind: a
window holds sentences, a parent holds children.
``chunk_textual`` returns chunks with a context sentence in front, which the
caller gets from a chat model first.

The strategies differ in the unit stream they start from, plus one packing rule:

``recursive``      structure units (headings and blank-line paragraphs), packed
                   to the window. This is the original algorithm, and it stays
                   the default so an existing product re-syncs to the same bytes.
``fixed``          no units. A hard window over the whole text, structure ignored.
``sentence``       sentences, packed to the window. The profile form no longer
                   offers it, because a sentence-level record is what
                   ``sentence_window`` stores; a stored row still reads.
``section``        one chunk per structure unit, cut further only when a unit is
                   larger than the window. The fanout asks the PDF path for the
                   document's own layout blocks for this strategy, so the writer
                   keeps a table region or a heading with the body it belongs to.
``layout``         the stored name this strategy had before the two were merged.
                   It still reads and still behaves like ``section``.
``context_aware``  sentences, grouped at topic shifts measured by embedding
                   similarity, then packed inside each group. A group boundary is
                   never crossed, so a chunk holds one topic. This is what the
                   profile form calls Semantic Chunking, and its breakpoint type
                   and amount come from ``config``.
``parent_child``   large parent blocks plus small child chunks. Both are stored,
                   and every child carries the reference of the parent it came
                   from, so a reader can return the child and then the surrounding
                   parent text without a second pass over the document.
``contextual``     recursive chunks, each with a short sentence in front that
                   places it in the document. The sentence comes from a chat
                   model, so the fanout builds it and calls ``chunk_textual``.
``page_level``     one chunk per page, so a page stays self-contained. A page over
                   its limit is cut on paragraph boundaries.
``sentence_window``each sentence on its own, plus the window of sentences around
                   it. The window is what supplies context for a matched sentence.

``chunk_overlap`` applies to the strategies that pack a window. It is a parameter,
not a strategy: the overlap window is what carries a sentence across a boundary,
and it never depends on how the boundary was chosen.
"""
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Structure units: a markdown heading line, or a blank line. The capture group
# keeps the separators in the result, which re.split does when a group matches.
_BLOCK_SPLIT = re.compile(r"(^#+\s+.*$|\n{2,})", flags=re.MULTILINE)
# A sentence ends at . ! or ? followed by whitespace and then a capital letter,
# digit, quote or bracket. That keeps "e.g. this" and "Inc. of" in one sentence
# without an abbreviation list. A heading marker also starts a unit, so packing a
# block list into sentences never leaves a stray "##" at the end of a chunk.
_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])"
    r"|(?<=\S)\s+(?=#+\s)"
)

# Child chunks are this fraction of the parent size. A small child matches a
# query closely, and its parent supplies the surrounding text. The fraction is
# clamped: never above half the parent, so a small chunk_size still produces two
# levels, and never below the floor, so a child stays a usable sentence group.
_PARENT_CHILD_RATIO = 3
_PARENT_CHILD_MIN_CHILD = 80
# A topic shift is a boundary whose cosine similarity sits more than this many
# standard deviations below the document mean. The profile overrides the number
# and the measure; this is the fallback when the stored config names neither.
_CONTEXT_DEFAULT_AMOUNT = 1.0
_CONTEXT_THRESHOLD_TYPES = ("standard_deviation", "percentile", "interquartile")
# Below this many sentences a mean and a standard deviation say nothing, so the
# strategy falls back to the size window alone.
_CONTEXT_MIN_SENTENCES = 6
# A page_level page is one record only while it stays inside the largest window the
# profile API allows. A longer page is cut, because one record holding a whole CSV
# or JSON dump is not a chunk a store or a reader can use.
_PAGE_LEVEL_CEILING = 8000

CHUNK_STRATEGIES: tuple[str, ...] = (
    "recursive",
    "fixed",
    "sentence",
    "section",
    "layout",
    "context_aware",
    "parent_child",
    "contextual",
    "page_level",
    "sentence_window",
)


@dataclass(frozen=True)
class ChunkPlan:
    """One record to store.

    ``record_type`` is ``chunk`` for a normal chunk, ``parent`` for a whole block
    in the parent_child strategy, ``child`` for a piece of one, ``window`` for the
    sentence group in sentence_window, and ``sentence`` for a sentence inside a
    window.
    ``parent_ordinal`` is the index of the parent record inside the same page,
    which the caller turns into a store reference once it knows the page number.
    """

    text: str
    record_type: str = "chunk"
    parent_ordinal: int | None = None


# ── Stored settings ──────────────────────────────────────────────────────────


def _config_float(
    config: Mapping[str, Any] | None,
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """One numeric setting, clamped to its bounds.

    A stored value can predate the bounds the form now enforces, and the chunker
    must not fail a file over it.
    """
    raw = (config or {}).get(key)
    try:
        number = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _config_str(
    config: Mapping[str, Any] | None, key: str, default: str, allowed: Sequence[str]
) -> str:
    """One named setting, or the default when the stored value is not one of them."""
    raw = (config or {}).get(key)
    value = str(raw) if raw is not None else ""
    return value if value in allowed else default


# ── Unit streams ─────────────────────────────────────────────────────────────


def _split_blocks(text: str) -> list[str]:
    """Headings and blank-line paragraphs, in order. The original unit stream."""
    return [token.strip() for token in _BLOCK_SPLIT.split(text) if token.strip()]


def _split_sentences(text: str) -> list[str]:
    return [token.strip() for token in _SENTENCE_SPLIT.split(text) if token.strip()]


def split_units(text: str, strategy: str) -> list[str]:
    """The units a strategy starts from, before any packing."""
    if strategy in {"sentence", "context_aware"}:
        return _split_sentences(text)
    if strategy in {"recursive", "section", "layout"}:
        return _split_blocks(text)
    if strategy == "fixed":
        return []
    raise ValueError(f"Unknown chunk strategy '{strategy}'")


# ── Packing ──────────────────────────────────────────────────────────────────


def _window_tail(current: list[str], chunk_overlap: int) -> tuple[list[str], int]:
    """The trailing units of ``current`` that fit inside the overlap window."""
    tail: list[str] = []
    tail_len = 0
    for token in reversed(current):
        if tail_len + len(token) < chunk_overlap:
            tail.insert(0, token)
            tail_len += len(token) + 1
        else:
            break
    return tail, tail_len


def _pack_units(units: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """Pack units into windows of ``chunk_size`` characters, overlapping by
    ``chunk_overlap``.

    This is the original ``chunk_text`` body. A unit larger than one window is
    cut on word boundaries, and the final window is left open so the next unit
    can fill it.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for unit in units:
        if len(unit) > chunk_size:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_length = 0
            sub: list[str] = []
            sub_len = 0
            for word in unit.split(" "):
                if sub_len + len(word) > chunk_size:
                    chunks.append(" ".join(sub))
                    sub = [word]
                    sub_len = len(word)
                else:
                    sub.append(word)
                    sub_len += len(word) + 1
            if sub:
                current = sub
                current_length = sub_len
            continue

        if current_length + len(unit) > chunk_size:
            chunks.append(" ".join(current))
            tail, tail_len = _window_tail(current, chunk_overlap)
            current = tail + [unit]
            current_length = tail_len + len(unit) + 1
        else:
            current.append(unit)
            current_length += len(unit) + 1

    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _split_fixed(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """A hard window that ignores structure. Overlap carries the tail words."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in text.split():
        if current and current_length + len(word) + 1 > chunk_size:
            chunks.append(" ".join(current))
            tail, tail_len = _window_tail(current, chunk_overlap)
            current = tail
            current_length = tail_len
        current.append(word)
        current_length += len(word) + 1

    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _split_by_unit(units: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """One chunk per unit. A unit larger than the window is cut, and no two units
    are ever merged. Overlap applies only inside a cut unit."""
    chunks: list[str] = []
    for unit in units:
        if len(unit) <= chunk_size:
            chunks.append(unit)
            continue
        chunks.extend(_split_fixed(unit, chunk_size, chunk_overlap))
    return [chunk for chunk in chunks if chunk.strip()]


def _pack_groups(
    units: list[str], bounds: set[int], chunk_size: int, chunk_overlap: int
) -> list[str]:
    """Pack each group of units on its own, so a group boundary is never crossed.

    ``bounds`` holds the unit indexes that start a new group.
    """
    chunks: list[str] = []
    group: list[str] = []
    for position, unit in enumerate(units):
        if position in bounds and group:
            chunks.extend(_pack_units(group, chunk_size, chunk_overlap))
            group = []
        group.append(unit)
    if group:
        chunks.extend(_pack_units(group, chunk_size, chunk_overlap))
    return chunks


# ── Context aware boundaries ─────────────────────────────────────────────────


def _percentile(values: Sequence[float], percent: float) -> float:
    """Linear-interpolated percentile, so the two ends are the min and the max."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * min(max(percent, 0.0), 100.0) / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _context_threshold(
    values: Sequence[float], threshold_type: str, amount: float
) -> float:
    """The similarity below which a boundary starts a new topic group.

    All three measures read ``amount`` the same way: a larger amount is the
    stricter test, so fewer boundaries and fewer, larger groups.
    """
    mean = sum(values) / len(values)
    if threshold_type == "percentile":
        # A boundary is a value BELOW the threshold, so a low percentile is the
        # strict test. The amount is inverted here, which is what keeps one field
        # meaning the same thing whichever measure the profile picks.
        return _percentile(values, 100.0 - amount * 30.0)
    if threshold_type == "interquartile":
        low = _percentile(values, 25.0)
        spread = _percentile(values, 75.0) - low
        return low - amount * spread
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean - amount * math.sqrt(variance)


def _context_bounds(
    units: list[str],
    similarities: Sequence[float],
    *,
    threshold_type: str = "standard_deviation",
    amount: float = _CONTEXT_DEFAULT_AMOUNT,
) -> set[int]:
    """Unit indexes that start a new topic, from adjacent-unit similarity.

    ``similarities[i]`` is the cosine similarity of unit ``i`` and unit ``i + 1``,
    so a boundary index is one greater than the unit it follows. A boundary is a
    topic shift when its similarity falls below the measure the profile names.
    """
    if len(units) < _CONTEXT_MIN_SENTENCES or len(similarities) < len(units) - 1:
        return set()
    values = [float(value) for value in similarities[: len(units) - 1]]
    if not values:
        return set()
    threshold = _context_threshold(values, threshold_type, amount)
    return {
        position + 1
        for position, value in enumerate(values)
        if value < threshold and position + 1 < len(units)
    }


# ── Public API ───────────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    strategy: str = "recursive",
    *,
    config: Mapping[str, Any] | None = None,
    similarities: Sequence[float] | None = None,
) -> list[str]:
    """Split one page of text into chunks with the named strategy.

    ``similarities`` holds the cosine similarity of each adjacent sentence pair
    and is read by ``context_aware`` alone. The caller computes it from the
    embedding model, because this function must stay synchronous.

    ``config`` holds the strategy's own stored settings. Only ``context_aware``
    reads one here.

    Three strategies do not come through this function, because their records are
    not all the same kind: the caller routes ``parent_child``,
    ``sentence_window`` and ``page_level`` to their own functions below.
    ``contextual`` reaches this function only without a context sentence, and then
    the chunks are the recursive ones.
    """
    if not text or not text.strip():
        return []

    if strategy == "fixed":
        return _split_fixed(text, chunk_size, chunk_overlap)

    if strategy in {"section", "layout"}:
        return _split_by_unit(split_units(text, strategy), chunk_size, chunk_overlap)

    if strategy == "contextual":
        return [plan.text for plan in chunk_textual(text, chunk_size, chunk_overlap)]

    units = split_units(text, strategy)
    if strategy == "context_aware":
        return _pack_groups(
            units,
            _context_bounds(
                units,
                similarities or [],
                threshold_type=_config_str(
                    config,
                    "semantic_threshold_type",
                    "standard_deviation",
                    _CONTEXT_THRESHOLD_TYPES,
                ),
                amount=_config_float(
                    config,
                    "semantic_threshold_amount",
                    _CONTEXT_DEFAULT_AMOUNT,
                    0.5,
                    3.0,
                ),
            ),
            chunk_size,
            chunk_overlap,
        )

    return _pack_units(units, chunk_size, chunk_overlap)


def chunk_textual(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    *,
    context: Mapping[int, str] | None = None,
) -> list[ChunkPlan]:
    """Recursive chunks, each with the context sentence written for it in front.

    ``context`` maps a chunk's position to the sentence that places it in its
    document. A position with no sentence stores the plain chunk, so a chat model
    that answered nothing degrades to Recursive Chunking instead of failing the
    file the chunk came from.
    """
    if not text or not text.strip():
        return []

    chunks = _pack_units(split_units(text, "recursive"), chunk_size, chunk_overlap)
    plans: list[ChunkPlan] = []
    for index, chunk in enumerate(chunks):
        prefix = ((context or {}).get(index) or "").strip()
        plans.append(ChunkPlan(text=f"{prefix}\n\n{chunk}" if prefix else chunk))
    return plans


def chunk_page(text: str, max_page_chars: int = 0) -> list[ChunkPlan]:
    """One record per page, which keeps a page whole and self-contained.

    ``max_page_chars`` of 0 means no limit, and the ceiling the profile API allows
    applies instead: a longer page is cut on paragraph boundaries, because a whole
    CSV or JSON dump is not a chunk a store or a reader can use.
    """
    if not text or not text.strip():
        return []

    limit = int(max_page_chars) if max_page_chars else _PAGE_LEVEL_CEILING
    return [
        ChunkPlan(text=chunk)
        for chunk in _pack_units(_split_blocks(text), limit, 0)
    ]


def chunk_sentence_window(text: str, window_sentences: int = 2) -> list[ChunkPlan]:
    """Windows of sentences, then every sentence inside each window.

    A window holds ``2 * window_sentences + 1`` sentences and the windows do not
    overlap, so a sentence belongs to exactly one of them. Windows come first and
    in order, because the caller numbers the records as they are returned and a
    sentence's ``parent_ordinal`` names the window that holds it.

    A window of one sentence is stored alone: the sentence record would be the
    same text, which doubles the store for nothing. That is the rule
    ``chunk_parent_child`` applies to a parent that fits inside one child.
    """
    if not text or not text.strip():
        return []

    span = max(1, int(window_sentences)) * 2 + 1
    sentences = _split_sentences(text)
    if not sentences:
        return []

    windows = [sentences[start : start + span] for start in range(0, len(sentences), span)]
    plans: list[ChunkPlan] = [
        ChunkPlan(text=" ".join(sentences_in), record_type="window") for sentences_in in windows
    ]
    for ordinal, sentences_in in enumerate(windows):
        if len(sentences_in) < 2:
            continue
        plans.extend(
            ChunkPlan(text=sentence, record_type="sentence", parent_ordinal=ordinal)
            for sentence in sentences_in
        )
    return plans


def chunk_parent_child(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    *,
    child_size: int | None = None,
    child_overlap: int = 0,
) -> list[ChunkPlan]:
    """Parent blocks of ``chunk_size``, each cut into small child chunks.

    Parents come first and in order, because the caller numbers the records in
    the order they are returned. A parent that fits inside one child window is
    stored alone: a child identical to its parent doubles the store for nothing.

    ``child_size`` of 0 or None derives the child window from the parent, which is
    what a profile that never set it asks for.
    """
    if not text or not text.strip():
        return []

    if child_size:
        child = max(_PARENT_CHILD_MIN_CHILD, min(int(child_size), chunk_size // 2))
    else:
        child = max(
            _PARENT_CHILD_MIN_CHILD,
            min(chunk_size // _PARENT_CHILD_RATIO, chunk_size // 2),
        )
    child_overlap = min(max(0, int(child_overlap or 0)), child - 1)
    parents = _pack_units(split_units(text, "recursive"), chunk_size, chunk_overlap)

    plans: list[ChunkPlan] = [ChunkPlan(text=parent, record_type="parent") for parent in parents]
    for ordinal, parent in enumerate(parents):
        children = _pack_units(split_units(parent, "sentence"), child, child_overlap)
        if len(children) < 2:
            continue
        plans.extend(
            ChunkPlan(text=child_text, record_type="child", parent_ordinal=ordinal)
            for child_text in children
        )
    return plans


def adjacent_similarities(
    vectors: Sequence[Sequence[float]],
) -> list[float]:
    """Cosine similarity of each adjacent pair. Returns one value fewer than the
    input, so index ``i`` describes the pair ``(i, i + 1)``."""
    out: list[float] = []
    for left, right in zip(vectors, vectors[1:]):
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        dot = sum(a * b for a, b in zip(left, right))
        out.append(dot / (left_norm * right_norm))
    return out


def sentence_splitter(text: str) -> list[str]:
    """The sentence unit stream, for a caller that needs to embed each sentence.

    Exported so the fanout computes similarities over exactly the units
    ``context_aware`` will group, and the two cannot drift apart.
    """
    return _split_sentences(text)


__all__ = [
    "CHUNK_STRATEGIES",
    "ChunkPlan",
    "adjacent_similarities",
    "chunk_page",
    "chunk_parent_child",
    "chunk_sentence_window",
    "chunk_text",
    "chunk_textual",
    "sentence_splitter",
    "split_units",
]
