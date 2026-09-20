import pytest

from src.ingestion_service.core.page_yielder import FilePage
from src.ingestion_service.core.universal_fanout import (
    _chunk_pages,
    _resolve_chunk_strategy,
    _resolve_chunking,
)
from src.ingestion_service.utils.text_splitter import (
    chunk_parent_child,
    chunk_text,
    split_units,
)
from src.shared.db.models import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_STRATEGY,
    ChunkStrategy,
    IngestionProfile,
    KnowledgeProduct,
)

_PARAGRAPH = "x" * 200


def _text(paragraphs: int) -> str:
    return "\n\n".join(_PARAGRAPH for _ in range(paragraphs))


def test_resolve_chunking_falls_back_without_a_profile() -> None:
    assert _resolve_chunking(KnowledgeProduct(name="t")) == (
        DEFAULT_CHUNK_SIZE,
        DEFAULT_CHUNK_OVERLAP,
    )


def test_resolve_chunking_reads_the_profile() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", chunk_size=200, chunk_overlap=20)

    assert _resolve_chunking(product) == (200, 20)


def test_resolve_chunking_clamps_an_overlap_at_the_size() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(name="p", chunk_size=200, chunk_overlap=500)

    assert _resolve_chunking(product) == (200, 199)


def test_chunk_pages_splits_a_page_and_numbers_the_chunks() -> None:
    pages = _chunk_pages([FilePage(page_index=3, text=_text(30))], 200, 20)

    assert len(pages) > 1
    assert all(page.page_index == 3 for page in pages)
    assert [page.chunk_index for page in pages] == list(range(len(pages)))


def test_chunk_pages_drops_a_blank_page() -> None:
    assert _chunk_pages([FilePage(page_index=0, text="")], 200, 20) == []


def test_chunk_pages_restarts_the_chunk_index_per_page() -> None:
    pages = _chunk_pages(
        [
            FilePage(page_index=0, text=_text(30)),
            FilePage(page_index=1, text=_text(30)),
            FilePage(page_index=2, text=_text(30)),
        ],
        200,
        20,
    )

    for page_index in (0, 1, 2):
        indexes = [p.chunk_index for p in pages if p.page_index == page_index]
        assert indexes == list(range(len(indexes)))


def test_chunk_pages_keeps_the_image_on_the_first_chunk_only() -> None:
    pages = _chunk_pages([FilePage(page_index=0, text=_text(30), image_png=b"png")], 200, 20)

    assert pages[0].image_png == b"png"
    assert all(page.image_png is None for page in pages[1:])


# ── Chunk strategies ─────────────────────────────────────────────────────────

_DOCUMENT = (
    "# Experience\n\n"
    "Senior engineer at Acme from 2019 to 2024. Led the platform team of six people. "
    "Shipped a payments service. Reduced p99 latency by 40 percent.\n\n"
    "## Education\n\n"
    "BSc Computer Science, 2015. First class honours. Thesis on graph databases.\n\n"
    "Python, Go, Postgres, Kubernetes, Terraform, Kafka, Redis, React, TypeScript."
)


def test_resolve_chunk_strategy_falls_back_without_a_profile() -> None:
    assert _resolve_chunk_strategy(KnowledgeProduct(name="t")) == DEFAULT_CHUNK_STRATEGY


def test_resolve_chunk_strategy_reads_the_profile() -> None:
    product = KnowledgeProduct(name="t")
    product.ingestion_profile = IngestionProfile(
        name="p", chunk_strategy=ChunkStrategy.PARENT_CHILD
    )

    assert _resolve_chunk_strategy(product) == "parent_child"


def test_the_default_strategy_is_still_the_recursive_one() -> None:
    """A product with no profile must chunk the way it did before the select."""
    assert chunk_text(_DOCUMENT, 200, 40) == chunk_text(_DOCUMENT, 200, 40, "recursive")


def test_section_keeps_every_block_whole() -> None:
    """One chunk per heading or paragraph, and never two blocks merged."""
    blocks = split_units(_DOCUMENT, "section")
    chunks = chunk_text(_DOCUMENT, 300, 20, "section")

    assert len(chunks) == len(blocks)
    assert chunks == blocks


def test_fixed_ignores_the_block_boundaries() -> None:
    """A hard window pays no attention to structure, so the cut lands mid-block."""
    fixed = chunk_text(_DOCUMENT, 200, 0, "fixed")

    assert len(fixed) > 1
    assert all(len(chunk) <= 200 for chunk in fixed)
    assert not any(chunk.strip() in split_units(_DOCUMENT, "recursive") for chunk in fixed)


def test_sentence_never_cuts_a_sentence_in_half() -> None:
    """Every chunk is a run of whole, consecutive sentences."""
    sentences = split_units(_DOCUMENT, "sentence")
    flat = [word for sentence in sentences for word in sentence.split(" ")]
    chunks = chunk_text(_DOCUMENT, 200, 0, "sentence")

    assert len(chunks) > 1
    cursor = 0
    for chunk in chunks:
        words = chunk.split(" ")
        assert flat[cursor : cursor + len(words)] == words, "chunk cut a sentence"
        cursor += len(words)
    assert cursor == len(flat)


def test_context_aware_starts_a_new_chunk_at_a_topic_shift() -> None:
    """Unit 4 follows a similarity dip, so a chunk boundary lands there."""
    text = ". ".join(f"Sentence number {n}" for n in range(10)) + "."
    similarities = [0.9, 0.9, 0.9, 0.05, 0.9, 0.9, 0.9, 0.9, 0.9]
    chunks = chunk_text(text, 8000, 0, "context_aware", similarities=similarities)

    assert len(chunks) == 2
    assert "Sentence number 4" in chunks[1]
    assert "Sentence number 4" not in chunks[0]


def test_context_aware_keeps_one_topic_in_one_chunk() -> None:
    text = ". ".join(f"Sentence number {n}" for n in range(10)) + "."
    chunks = chunk_text(text, 8000, 0, "context_aware", similarities=[0.9] * 9)

    assert len(chunks) == 1


def test_context_aware_falls_back_to_the_window_without_similarities() -> None:
    """An unreachable embedding model must not change the number of chunks."""
    with_similarities = chunk_text(_DOCUMENT, 120, 0, "context_aware", similarities=[0.1] * 40)
    without = chunk_text(_DOCUMENT, 120, 0, "context_aware")

    assert len(without) > 1
    # A 0.1 similarity everywhere is a shift at every boundary, so the two differ
    # only in how the groups are cut, never in losing text.
    assert "".join(without).replace(" ", "") == "".join(with_similarities).replace(" ", "")


def test_parent_child_stores_the_parent_and_its_children() -> None:
    plans = chunk_parent_child(_DOCUMENT, 200, 40)
    parents = [p for p in plans if p.record_type == "parent"]
    children = [p for p in plans if p.record_type == "child"]

    assert parents and children
    assert all(child.parent_ordinal is not None for child in children)
    assert all(
        len(child.text) < len(parents[child.parent_ordinal].text)
        for child in children
    )


def test_parent_child_keeps_a_short_block_as_one_parent() -> None:
    """A parent that fits inside one child window is stored alone."""
    plans = chunk_parent_child("Short resume text.", 1000, 100)

    assert [p.record_type for p in plans] == ["parent"]


def test_parent_child_children_resolve_to_a_real_parent_record() -> None:
    """The parent ordinal must address a parent, because the fanout turns it into
    a store reference of ``<page_index>:<chunk_index>``."""
    doc = "\n\n".join(
        " ".join(f"Sentence {n} of block {b}." for n in range(12)) for b in range(3)
    )
    pages = _chunk_pages([FilePage(page_index=5, text=doc)], 400, 40, "parent_child")
    by_index = {page.chunk_index: page for page in pages}
    children = [page for page in pages if page.record_type == "child"]

    assert children
    for child in children:
        parent_index = int(child.parent_ref.split(":")[1])
        assert child.parent_ref.startswith("5:")
        assert by_index[parent_index].record_type == "parent"


def test_chunk_pages_numbers_parents_before_their_children() -> None:
    doc = "\n\n".join(
        " ".join(f"Sentence {n} of block {b}." for n in range(12)) for b in range(2)
    )
    pages = _chunk_pages([FilePage(page_index=0, text=doc)], 300, 30, "parent_child")

    kinds = [page.record_type for page in pages]
    assert [page.chunk_index for page in pages] == list(range(len(pages)))
    assert kinds.index("child") > kinds.index("parent")
    assert set(kinds) == {"parent", "child"}


def test_an_unknown_strategy_raises_rather_than_chunking_silently() -> None:
    with pytest.raises(ValueError):
        split_units(_DOCUMENT, "semantic_magic")
