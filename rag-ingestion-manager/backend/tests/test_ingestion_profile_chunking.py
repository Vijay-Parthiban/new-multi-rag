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


def test_parent_child_honours_an_explicit_child_size() -> None:
    """A profile that sets a child window gets it, up to half the parent size."""
    doc = "\n\n".join(
        " ".join(f"Sentence {n} of block {b}." for n in range(12)) for b in range(2)
    )
    default_children = [
        plan for plan in chunk_parent_child(doc, 600, 40) if plan.record_type == "child"
    ]
    small_children = [
        plan
        for plan in chunk_parent_child(doc, 600, 40, child_size=100, child_overlap=20)
        if plan.record_type == "child"
    ]

    assert all(len(plan.text) <= 300 for plan in default_children)
    assert all(len(plan.text) <= 100 for plan in small_children)
    assert len(small_children) > len(default_children)


def test_semantic_breakpoint_amount_moves_the_boundary() -> None:
    """One field, one meaning: a larger amount makes fewer, larger groups."""
    text = ". ".join(f"Sentence number {n}" for n in range(12)) + "."
    similarities = [0.9, 0.8, 0.7, 0.3, 0.2, 0.9, 0.8, 0.7, 0.3, 0.2, 0.9]
    config = {"semantic_threshold_type": "percentile"}

    many = chunk_text(
        text, 8000, 0, "context_aware", similarities=similarities,
        config={**config, "semantic_threshold_amount": 0.5},
    )
    few = chunk_text(
        text, 8000, 0, "context_aware", similarities=similarities,
        config={**config, "semantic_threshold_amount": 3.0},
    )

    assert len(many) > len(few)


def test_semantic_threshold_falls_back_on_a_bad_stored_value() -> None:
    """A stored value that names no measure must not fail the file."""
    text = ". ".join(f"Sentence number {n}" for n in range(10)) + "."
    similarities = [0.9, 0.9, 0.9, 0.05, 0.9, 0.9, 0.9, 0.9, 0.9]
    default = chunk_text(text, 8000, 0, "context_aware", similarities=similarities)
    broken = chunk_text(
        text,
        8000,
        0,
        "context_aware",
        similarities=similarities,
        config={"semantic_threshold_type": "nonsense", "semantic_threshold_amount": "x"},
    )

    assert broken == default


def test_page_level_stores_one_record_per_page() -> None:
    from src.ingestion_service.utils.text_splitter import chunk_page

    assert len(chunk_page("A short page.")) == 1
    assert len(chunk_page("word " * 4000)) > 1


def test_page_level_cuts_a_long_page_on_paragraph_boundaries() -> None:
    page = "\n\n".join(f"Paragraph {n} " + "x" * 200 for n in range(10))
    pages = _chunk_pages(
        [FilePage(page_index=0, text=page)], 1000, 100, "page_level", {"max_page_chars": 500}
    )

    assert len(pages) > 1
    assert all(len(part.text) <= 600 for part in pages)
    assert [part.chunk_index for part in pages] == list(range(len(pages)))


def test_sentence_window_stores_windows_before_their_sentences() -> None:
    doc = " ".join(f"Sentence number {n}." for n in range(9))
    pages = _chunk_pages(
        [FilePage(page_index=0, text=doc)], 1000, 0, "sentence_window", {"window_sentences": 1}
    )
    kinds = [page.record_type for page in pages]
    by_index = {page.chunk_index: page for page in pages}
    sentences = [page for page in pages if page.record_type == "sentence"]

    assert kinds.count("window") == 3
    assert len(sentences) == 9
    assert kinds.index("sentence") > kinds.index("window")
    for sentence in sentences:
        parent_index = int(sentence.parent_ref.split(":")[1])
        assert sentence.parent_ref.startswith("0:")
        assert by_index[parent_index].record_type == "window"
        assert sentence.text in by_index[parent_index].text


def test_contextual_puts_the_context_sentence_in_front() -> None:
    from src.ingestion_service.utils.text_splitter import chunk_textual

    plans = chunk_textual(_DOCUMENT, 200, 0, context={0: "A resume of one engineer."})

    assert plans[0].text.startswith("A resume of one engineer.\n\n")
    assert all(plan.record_type == "chunk" for plan in plans)


def test_contextual_without_a_context_keeps_the_recursive_chunks() -> None:
    """A chat model that answered nothing must not fail the file."""
    from src.ingestion_service.utils.text_splitter import chunk_textual

    plain = [p.text for p in chunk_textual(_DOCUMENT, 200, 0)]
    with_context = _chunk_pages(
        [FilePage(page_index=0, text=_DOCUMENT)], 200, 0, "contextual", None, None, {}
    )

    assert [p.text for p in with_context] == plain
    assert plain == chunk_text(_DOCUMENT, 200, 0)


def test_validate_chunk_config_accepts_the_empty_config() -> None:
    from apps.api.routes.chunk_strategies import validate_chunk_config

    assert validate_chunk_config("recursive", None) == []
    assert validate_chunk_config("recursive", {}) == []
    assert validate_chunk_config("sentence_window", {"window_sentences": 3}) == []


def test_validate_chunk_config_rejects_an_unknown_key_and_a_bad_range() -> None:
    from apps.api.routes.chunk_strategies import validate_chunk_config

    unknown = validate_chunk_config("sentence_window", {"bogus": 1})
    out_of_range = validate_chunk_config("sentence_window", {"window_sentences": 99})
    bad_select = validate_chunk_config("context_aware", {"semantic_threshold_type": "mean"})

    assert unknown and "bogus" in unknown[0]
    assert out_of_range and "Window Sentences" in out_of_range[0]
    assert bad_select and "Breakpoint Type" in bad_select[0]


def test_validate_chunk_config_leaves_a_retired_strategy_alone() -> None:
    """A profile stored before the strategy list changed must still save.

    ``layout`` is no longer offered, so its stored config has no catalogue to check
    against, and refusing it would lock the row.
    """
    from apps.api.routes.chunk_strategies import validate_chunk_config

    assert validate_chunk_config("layout", {"anything": 1}) == []
    assert validate_chunk_config("sentence", {"anything": 1}) == []


def test_an_unknown_strategy_raises_rather_than_chunking_silently() -> None:
    with pytest.raises(ValueError):
        split_units(_DOCUMENT, "semantic_magic")
