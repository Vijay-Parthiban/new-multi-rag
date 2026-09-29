"""The golden-source matcher: the page suffix, name matching, and page matching.

These pin the convention a CSV has to follow. Before the page suffix existed, an
uploaded CSV could not express a page at all — the JSON form supports `{name, page}`
objects, but `source_doc_id` maps to plain strings, so the page was unreachable. Every
reference-based metric then read zero for a dataset whose sources named a page.
"""

from eval_core.source_match import (
    ExpectedSource,
    matches_expected_source,
    normalize_source,
    parse_expected_sources,
)
from rag_shared.types import RetrievedChunk

WHISTLE = "TCS-Global-Whistle-Blower-Policy.pdf"


def chunk(page_index: int | None, name: str = WHISTLE) -> RetrievedChunk:
    """A retrieved chunk as the reader returns it: a connector path plus a page index."""
    return RetrievedChunk(
        id="c1",
        content="text",
        chunk_type="text",
        source_type="file_ingest",
        source_id="s1",
        chunk_index=0,
        retrieval_score=1.0,
        source_locator=f"connectors/aa/bb/{name}",
        title=name,
        metadata={"file_name": name, "page_index": page_index},
    )


# --- the page suffix -----------------------------------------------------------------


def test_a_page_suffix_becomes_the_page():
    parsed = parse_expected_sources([f"{WHISTLE}_p3"])

    assert parsed == [ExpectedSource(name=WHISTLE, page=3)]


def test_a_name_without_a_suffix_keeps_no_page():
    parsed = parse_expected_sources([WHISTLE])

    assert parsed == [ExpectedSource(name=WHISTLE, page=None)]


def test_a_dict_entry_still_carries_its_page():
    """The JSON form already had this; the suffix must not break it."""
    parsed = parse_expected_sources([{"name": WHISTLE, "page": 2}])

    assert parsed == [ExpectedSource(name=WHISTLE, page=2)]


def test_a_suffix_without_digits_is_part_of_the_name():
    """`my_pdf` is a name, not a page. Only `_p<digits>` splits."""
    parsed = parse_expected_sources(["my_pdf"])

    assert parsed == [ExpectedSource(name="my_pdf", page=None)]


# --- name matching -------------------------------------------------------------------


def test_the_basename_of_a_connector_path_matches_the_file_name():
    """The corpus stores `connectors/<id>/<id>/<file>`. The match is on the basename."""
    assert normalize_source(f"connectors/aa/bb/{WHISTLE}") == WHISTLE.lower()


def test_a_real_file_name_matches():
    assert matches_expected_source(chunk(2), parse_expected_sources([WHISTLE])[0])


def test_a_shorthand_label_does_not_match():
    """`WB` names no part of the file, so it cannot match. This is the check that would
    have caught the dataset whose every source read zero."""
    assert not matches_expected_source(chunk(2), parse_expected_sources(["WB_p3"])[0])


# --- page matching -------------------------------------------------------------------


def test_the_page_suffix_is_one_based_against_page_index():
    """`metadata.page_index` is 0-based, the suffix is 1-based: _p3 is page_index 2."""
    assert matches_expected_source(chunk(2), parse_expected_sources([f"{WHISTLE}_p3"])[0])
    assert not matches_expected_source(chunk(3), parse_expected_sources([f"{WHISTLE}_p3"])[0])


def test_a_name_without_a_page_ignores_the_page():
    assert matches_expected_source(chunk(7), parse_expected_sources([WHISTLE])[0])


def test_a_chunk_with_no_page_fails_a_paged_source():
    assert not matches_expected_source(chunk(None), parse_expected_sources([f"{WHISTLE}_p3"])[0])
