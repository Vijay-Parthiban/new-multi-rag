from dataclasses import dataclass
from typing import Literal

EmbeddingSource = Literal["markdown", "image"]

WEB_SCRAPE_SOURCE_TYPE = "web_scrape"
FILE_INGEST_SOURCE_TYPE = "file_ingest"

SourceType = Literal["web_scrape", "file_ingest"]
SourceTypeFilter = Literal["all", "web_scrape", "file_ingest"]


@dataclass
class DiscoveredLink:
    url: str
    depth: int
    parent: str | None
    status_code: int | None = None


@dataclass
class ScrapedPage:
    url: str
    title: str | None
    text: str
    html: str


@dataclass
class CrawlLinkRecord:
    url: str
    depth: int
    parent: str | None = None
    status_code: int | None = None


@dataclass
class ScrapePageResult:
    url: str
    title: str | None
    markdown_path: str
    screenshot_path: str
    depth: int
