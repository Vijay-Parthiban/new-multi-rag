"""Per-source webscraping: the manifest rule, the object keys, and what the fanout ignores."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx

from src.ingestion_service.core.webscrape import (
    _is_stale,
    drop_webscrape_control_objects,
    image_object_key,
    is_webscrape_manifest,
    output_prefix_for,
    page_object_key,
    parse_seeds,
    scrape_error_detail,
)
from src.shared.config.settings import Settings


def test_manifest_detection_is_case_insensitive_and_suffix_only() -> None:
    assert is_webscrape_manifest("sites_scrp.txt")
    assert is_webscrape_manifest("connectors/abc/docs/SITES_SCRP.TXT")
    assert not is_webscrape_manifest("sites_scrp.txt.bak")
    assert not is_webscrape_manifest("scrp.txt")
    assert not is_webscrape_manifest("sites.txt")


def test_run_folder_sits_under_the_run_root() -> None:
    # Not beside the manifest: a connector sync deletes everything under its own prefix.
    assert output_prefix_for("sites_scrp.txt") == "webscrape/sites_scrp/"
    assert output_prefix_for("connectors/abc/docs/sites_scrp.txt") == (
        "webscrape/connectors/abc/docs/sites_scrp/"
    )


def test_generated_keys_are_ordered_and_url_slugged() -> None:
    prefix = "webscrape/connectors/abc/docs/sites_scrp/"
    assert page_object_key(prefix, 0, "https://example.com/") == (
        "webscrape/connectors/abc/docs/sites_scrp/page-00000-https-example-com.md"
    )
    # Long URLs are cut short so one page cannot make an unbounded object name.
    long_key = page_object_key(prefix, 7, "https://example.com/" + "a" * 400)
    assert long_key.startswith("webscrape/connectors/abc/docs/sites_scrp/page-00007-https-example-com-")
    assert len(long_key) < 190
    assert image_object_key("webscrape/sites_scrp/", 1, "https://example.com/a") == (
        "webscrape/sites_scrp/images/page-00001-https-example-com-a.png"
    )


def test_parse_seeds_keeps_only_unique_http_urls() -> None:
    raw = (
        b"# a comment\n"
        b"https://one.example\n"
        b"\n"
        b"  http://two.example/path  \n"
        b"https://one.example\n"
        b"ftp://three.example\n"
        b"not a url\n"
    )
    assert parse_seeds(raw) == ["https://one.example", "http://two.example/path"]


def test_parse_seeds_strips_a_byte_order_mark_and_survives_bad_bytes() -> None:
    # A Windows editor writes a BOM; it must not hide the first URL.
    assert parse_seeds(b"\xef\xbb\xbfhttps://one.example\nhttps://two.example\n") == [
        "https://one.example",
        "https://two.example",
    ]
    # Bytes that are not UTF-8 must not raise. The damaged line is skipped.
    raw = b"\xff\xfe html\nhttps://three.example\n"
    assert parse_seeds(raw) == ["https://three.example"]


def test_fanout_drops_the_manifest_and_its_non_markdown_objects() -> None:
    remote = {
        "guide.pdf": ("e1", 10, object()),
        "sites_scrp.txt": ("e2", 20, object()),
        "webscrape/sites_scrp/page-00000-https-example-com.md": ("e3", 30, object()),
        "webscrape/sites_scrp/page-00001-https-example-com-a.md": ("e4", 40, object()),
        "webscrape/sites_scrp/images/page-00000-https-example-com.png": ("e5", 50, object()),
        "connectors/abc/docs/other_scrp.txt": ("e6", 60, object()),
        "webscrape/connectors/abc/docs/other_scrp/page-00000-x.md": ("e7", 70, object()),
        "webscrape/connectors/abc/docs/other_scrp/images/page-00000-x.png": ("e8", 80, object()),
    }

    dropped = drop_webscrape_control_objects(remote)

    assert dropped == 4
    assert sorted(remote) == [
        "guide.pdf",
        "webscrape/connectors/abc/docs/other_scrp/page-00000-x.md",
        "webscrape/sites_scrp/page-00000-https-example-com.md",
        "webscrape/sites_scrp/page-00001-https-example-com-a.md",
    ]


def test_fanout_leaves_a_listing_without_a_manifest_alone() -> None:
    remote = {"guide.pdf": ("e1", 10, object()), "webscrape/sites_scrp/page-x.md": ("e2", 20, object())}

    assert drop_webscrape_control_objects(remote) == 0
    assert sorted(remote) == ["guide.pdf", "webscrape/sites_scrp/page-x.md"]


def test_transport_error_names_the_scraper_and_its_url() -> None:
    detail = scrape_error_detail(httpx.ConnectError("All connection attempts failed"))

    assert "scraper API" in detail
    assert "http://" in detail
    assert "All connection attempts failed" not in detail
    # A non-transport error keeps its own text, which is what the scraper sent.
    assert scrape_error_detail(RuntimeError("scrape job ended as failed")) == (
        "scrape job ended as failed"
    )


def test_is_stale_only_after_a_run_could_have_died() -> None:
    """A live poller calls the scan often, so a mid-run row must not look retryable."""
    settings = Settings()
    fresh = SimpleNamespace(updated_at=datetime.now(UTC) - timedelta(seconds=60))
    dead = SimpleNamespace(
        updated_at=datetime.now(UTC)
        - timedelta(seconds=settings.webscrape_job_timeout_seconds + 600)
    )

    assert _is_stale(fresh, settings) is False
    assert _is_stale(dead, settings) is True
    # A row that never recorded an update cannot be running, so it may be retried.
    assert _is_stale(SimpleNamespace(updated_at=None), settings) is True
