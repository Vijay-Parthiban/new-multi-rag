import httpx
import pytest
from crawler_shared.types import DiscoveredLink
from crawler_shared.storage.links_file import LinksFileWriter
from web_crawler.core.engine import CrawlerEngine
from web_crawler.core.link_extractor import LinkExtractor
from web_crawler.utils.url import extract_links, is_same_domain, normalize_url


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert normalize_url("https://Example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/") == "https://example.com"


def test_is_same_domain():
    assert is_same_domain("https://example.com", "https://example.com/about")
    assert not is_same_domain("https://example.com", "https://other.com")


def test_extract_links_from_html():
    html = (
        '<html><body>'
        '<a href="/manual.pdf">PDF</a>'
        '<a href="https://other.com/image.png">PNG</a>'
        '<a href="/index.asp">ASP</a>'
        "</body></html>"
    )
    links = extract_links(html, "https://example.com")
    assert "https://example.com/manual.pdf" in links
    assert "https://other.com/image.png" in links
    assert "https://example.com/index.asp" in links


def test_links_file_writer_roundtrip(tmp_path):
    writer = LinksFileWriter(tmp_path)
    links = [
        DiscoveredLink(url="https://example.com", depth=0, parent=None, status_code=200),
        DiscoveredLink(url="https://example.com/about", depth=1, parent="https://example.com", status_code=200),
    ]
    path = writer.write("job-1", links)
    loaded = list(LinksFileWriter.read(path))
    assert len(loaded) == 2
    assert loaded[0].url == "https://example.com"


def test_crawler_engine_respects_max_pages():
    pages = {
        "https://example.com": '<a href="https://example.com/a">a</a><a href="https://example.com/guide.pdf">pdf</a>',
        "https://example.com/a": '<a href="https://example.com/image.png">png</a>',
        "https://example.com/guide.pdf": "",
        "https://example.com/image.png": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).rstrip("/")
        normalized = normalize_url(url)
        html = pages.get(normalized, "")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    engine = CrawlerEngine(max_depth=3, max_pages=2, client=client)
    links = engine.crawl("https://example.com")
    # We record fetched pages. With max_pages=2, we fetch seed + one more page.
    urls = [link.url for link in links]
    assert urls[0] == "https://example.com"
    assert len(urls) == 2


def test_crawler_engine_respects_max_depth():
    pages = {
        "https://example.com": '<a href="https://example.com/child">child</a>',
        "https://example.com/child": '<a href="https://example.com/grandchild.docx">grandchild</a>',
        "https://example.com/grandchild.docx": "",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = normalize_url(str(request.url))
        return httpx.Response(200, text=pages.get(url, ""), headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    engine = CrawlerEngine(max_depth=1, max_pages=10, client=client)
    links = engine.crawl("https://example.com")
    urls = {link.url for link in links}
    assert "https://example.com" in urls
    assert "https://example.com/child" in urls
    assert "https://example.com/grandchild.docx" not in urls


def test_crawler_engine_auto_mode_falls_back_to_playwright_for_js_shell(monkeypatch: pytest.MonkeyPatch):
    pages = {
        "https://example.com": '<html><body><div id="root"></div><script src="/app.js"></script></body></html>',
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = normalize_url(str(request.url))
        html = pages.get(url, "")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    def fake_playwright_fetch(self: LinkExtractor, _url: str) -> tuple[str | None, int | None]:
        rendered_html = '<html><body><a href="/from-js.pdf">from js</a></body></html>'
        return rendered_html, 200

    monkeypatch.setattr(LinkExtractor, "_fetch_with_playwright", fake_playwright_fetch)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    engine = CrawlerEngine(max_depth=1, max_pages=10, client=client, fetch_mode="auto")
    links = engine.crawl("https://example.com")
    urls = {link.url for link in links}

    assert "https://example.com" in urls
    assert "https://example.com/from-js.pdf" in urls


def test_crawler_engine_rejects_invalid_fetch_mode():
    with pytest.raises(ValueError, match="fetch_mode must be one of: httpx, playwright, auto"):
        CrawlerEngine(max_depth=1, max_pages=10, fetch_mode="invalid")
