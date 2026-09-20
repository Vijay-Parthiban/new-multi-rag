"""Chunking strategies for the fanout and the legacy Pipeline path.

Two entry points, because the two shapes of output differ:

``chunk_text`` returns a flat list of chunk strings for one page. Six of the
seven strategies use it.
``chunk_parent_child`` returns parent and child plans, because the two levels are
stored as separate records and a child must name its parent.

The strategies differ in the unit stream they start from, plus one packing rule:

``recursive``      structure units (headings and blank-line paragraphs), packed
                   to the window. This is the original algorithm, and it stays
                   the default so an existing product re-syncs to the same bytes.
``fixed``          no units. A hard window over the whole text, structure ignored.
``sentence``       sentences, packed to the window.
``section``        one chunk per structure unit, cut further only when a unit is
                   larger than the window.
``layout``         like ``section``, but the PDF path supplies the document's own
                   layout blocks as the units, so the writer keeps a table region
                   or a heading with the body it belongs to. A non-PDF format has
                   no layout blocks, so the units match ``section``.
``context_aware``  sentences, grouped at topic shifts measured by embedding
                   similarity, then packed inside each group. A group boundary is
                   never crossed, so a chunk holds one topic.
``parent_child``   large parent blocks plus small child chunks. Both are stored,
                   and every child carries the reference of the parent it came
                   from, so a reader can return the child and then the surrounding
                   parent text without a second pass over the document.

``chunk_overlap`` applies to every strategy. It is a parameter, not a strategy:
the overlap window is what carries a sentence across a boundary, and it never
depends on how the boundary was chosen.
"""
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

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
# A topic shift is a boundary whose cosine similarity sits this many standard
# deviations below the document mean. ponytail: a per-document statistic, so no
# threshold has to be tuned for each corpus. Expose it as a field only if a real
# document reports the wrong boundaries.
_CONTEXT_SHIFT_SIGMA = 1.0
# Below this many sentences a mean and a standard deviation say nothing, so the
# strategy falls back to the size window alone.
_CONTEXT_MIN_SENTENCES = 6

CHUNK_STRATEGIES: tuple[str, ...] = (
    "recursive",
    "fixed",
    "sentence",
    "section",
    "layout",
    "context_aware",
    "parent_child",
)


@dataclass(frozen=True)
class ChunkPlan:
    """One record to store.

    ``record_type`` is ``chunk`` for a normal chunk, ``parent`` for a whole block
    in the parent_child strategy, and ``child`` for a piece of one.
    ``parent_ordinal`` is the index of the parent record inside the same page,
    which the caller turns into a store reference once it knows the page number.
    """

    text: str
    record_type: str = "chunk"
    parent_ordinal: int | None = None


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


def _context_bounds(units: list[str], similarities: Sequence[float]) -> set[int]:
    """Unit indexes that start a new topic, from adjacent-unit similarity.

    ``similarities[i]`` is the cosine similarity of unit ``i`` and unit ``i + 1``,
    so a boundary index is one greater than the unit it follows. A boundary is a
    topic shift when its similarity sits more than one standard deviation below
    the document mean.
    """
    if len(units) < _CONTEXT_MIN_SENTENCES or len(similarities) < len(units) - 1:
        return set()
    values = [float(value) for value in similarities[: len(units) - 1]]
    if not values:
        return set()
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    threshold = mean - _CONTEXT_SHIFT_SIGMA * math.sqrt(variance)
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
    similarities: Sequence[float] | None = None,
) -> list[str]:
    """Split one page of text into chunks with the named strategy.

    ``similarities`` holds the cosine similarity of each adjacent sentence pair
    and is read by ``context_aware`` alone. The caller computes it from the
    embedding model, because this function must stay synchronous.
    """
    if not text or not text.strip():
        return []

    if strategy == "fixed":
        return _split_fixed(text, chunk_size, chunk_overlap)

    if strategy in {"section", "layout"}:
        return _split_by_unit(split_units(text, strategy), chunk_size, chunk_overlap)

    units = split_units(text, strategy)
    if strategy == "context_aware":
        return _pack_groups(
            units, _context_bounds(units, similarities or []), chunk_size, chunk_overlap
        )

    return _pack_units(units, chunk_size, chunk_overlap)


def chunk_parent_child(
    text: str, chunk_size: int = 1000, chunk_overlap: int = 100
) -> list[ChunkPlan]:
    """Parent blocks of ``chunk_size``, each cut into small child chunks.

    Parents come first and in order, because the caller numbers the records in
    the order they are returned. A parent that fits inside one child window is
    stored alone: a child identical to its parent doubles the store for nothing.
    """
    if not text or not text.strip():
        return []

    child_size = max(
        _PARENT_CHILD_MIN_CHILD,
        min(chunk_size // _PARENT_CHILD_RATIO, chunk_size // 2),
    )
    child_overlap = min(chunk_overlap, child_size - 1)
    parents = _pack_units(split_units(text, "recursive"), chunk_size, chunk_overlap)

    plans: list[ChunkPlan] = [ChunkPlan(text=parent, record_type="parent") for parent in parents]
    for ordinal, parent in enumerate(parents):
        children = _pack_units(split_units(parent, "sentence"), child_size, child_overlap)
        if len(children) < 2:
            continue
        plans.extend(
            ChunkPlan(text=child, record_type="child", parent_ordinal=ordinal)
            for child in children
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
    "chunk_parent_child",
    "chunk_text",
    "sentence_splitter",
    "split_units",
]
