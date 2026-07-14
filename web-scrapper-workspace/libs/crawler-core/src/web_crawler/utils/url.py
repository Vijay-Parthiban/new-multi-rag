from __future__ import annotations

import logging
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ALLOWED_NON_WEB_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
}


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.

    Current normalization rules:
    - lower-case scheme and host
    - strip a single trailing slash from non-root paths
    - treat `/` as empty path so `https://x/` becomes `https://x`
    - keep query string
    - drop fragment
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "http"
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")
    normalized = urlunparse((scheme, netloc, path, "", parsed.query, ""))
    return normalized


def is_same_domain(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    return base.netloc.lower() == candidate.netloc.lower()


def is_http_url(url: str) -> bool:
    """Return True if URL scheme is http/https."""
    scheme = urlparse(url).scheme.lower()
    return scheme in {"http", "https"}


def is_allowed_non_web_resource(url: str) -> bool:
    """Return True if URL path ends with an allowed file extension (pdf/png/docx/...).

    This is used to decide whether a URL should be *recorded* as a crawl result
    (links file), not whether it can be traversed.
    """
    path = urlparse(url).path.lower()
    if "." not in path:
        return False
    extension = "." + PurePosixPath(path).suffix.lstrip(".")
    if extension == ".":  # no suffix
        return False
    return extension in ALLOWED_NON_WEB_EXTENSIONS


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract and normalize all http(s) anchor links from HTML.

    Notes:
    - Returns *all* http(s) links so the crawler can traverse HTML pages.
    - Filtering to non-web resources (pdf/png/docx/...) is handled elsewhere.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if not is_http_url(absolute):
            continue
        normalized = normalize_url(absolute)
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    logger.debug("extract_links base=%s extracted=%d", base_url, len(links))
    return links
